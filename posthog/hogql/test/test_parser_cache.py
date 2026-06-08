from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import (
    _MAX_CACHEABLE_STATEMENT_LEN,
    _MIN_CACHEABLE_STATEMENT_LEN,
    CacheOrigin,
    _builtin_parse_cache,
    _looks_like_code_literal,
    _user_parse_cache,
    clear_parse_caches,
    parse_expr,
    parse_select,
    parse_string_template,
)


class TestParserCache(BaseTest):
    def setUp(self):
        super().setUp()
        clear_parse_caches()

    def _total_cache_size(self) -> int:
        return int(_builtin_parse_cache.currsize + _user_parse_cache.currsize)

    def test_cache_hit_returns_equivalent_ast(self):
        sql = "SELECT count() FROM events WHERE event = '$pageview' -- cache test"
        first = parse_select(sql)
        second = parse_select(sql)
        self.assertEqual(first, second)
        # Verify the second call was actually a cache hit, not a re-parse.
        self.assertEqual(self._total_cache_size(), 1)

    def test_cache_hit_returns_distinct_object(self):
        # The resolver and printer mutate the AST in place — cache hits must
        # not share node identity with previous returns.
        sql = "SELECT count() FROM events WHERE event = '$pageview' -- distinct test"
        first = parse_select(sql)
        second = parse_select(sql)
        self.assertIsNot(first, second)
        self.assertEqual(self._total_cache_size(), 1)

    def test_mutation_does_not_leak_across_calls(self):
        sql = "SELECT 1 FROM events WHERE event = '$exception' -- mutation isolation"
        first = parse_select(sql)
        assert isinstance(first, ast.SelectQuery)
        first.limit = ast.Constant(value=10)
        second = parse_select(sql)
        assert isinstance(second, ast.SelectQuery)
        self.assertIsNone(second.limit)
        # The second call must have hit the cache; otherwise mutation isolation
        # is trivially satisfied by re-parsing, which isn't what we're testing.
        self.assertEqual(self._total_cache_size(), 1)

    @parameterized.expand(
        [
            (CacheOrigin.BUILTIN, lambda: _builtin_parse_cache, lambda: _user_parse_cache),
            (CacheOrigin.USER, lambda: _user_parse_cache, lambda: _builtin_parse_cache),
        ]
    )
    def test_explicit_origin_routes_to_matching_cache(self, origin, target_getter, other_getter):
        parse_select(f"SELECT 1 -- routing test {origin}, plenty long enough to cache", cache_origin=origin)
        self.assertEqual(target_getter().currsize, 1)
        self.assertEqual(other_getter().currsize, 0)

    def test_auto_detects_function_local_literal(self):
        # Literal must be long enough to bypass the auto-interning guard
        # (`_LITERAL_DETECTION_MIN_LEN`).
        parse_select("SELECT count() FROM events WHERE event = '$exception'")
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_auto_routes_constructed_strings_to_user_cache(self):
        # `.join` produces a fresh runtime string. Concat of two string
        # literals (`"a " + "b"`) would be folded by the compiler into a
        # single literal and incorrectly look built-in.
        sql = " ".join(["SELECT", "count()", "FROM", "events", "WHERE", "event", "=", "'$pageview'"])
        parse_select(sql)
        self.assertEqual(_user_parse_cache.currsize, 1)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    def test_user_pollution_does_not_displace_builtin(self):
        parse_select(
            "SELECT 'builtin entry' -- pollution test, plenty long enough to cache",
            cache_origin=CacheOrigin.BUILTIN,
        )
        user_maxsize = int(_user_parse_cache.maxsize)
        for i in range(user_maxsize + 50):
            parse_select(
                f"SELECT {i} -- pollution test row, plenty long enough to cache", cache_origin=CacheOrigin.USER
            )
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, user_maxsize)

    def test_different_placeholders_share_cache_entry(self):
        # Cache key is the raw SQL; placeholders are substituted on the
        # deepcopy returned from cache. The whole templated-query workload
        # depends on this sharing — assert it explicitly.
        sql = "SELECT {x} FROM events WHERE event = '$pageview' LIMIT {n}"

        first = parse_select(sql, placeholders={"x": ast.Constant(value=1), "n": ast.Constant(value=10)})
        self.assertEqual(_builtin_parse_cache.currsize + _user_parse_cache.currsize, 1)
        assert isinstance(first, ast.SelectQuery)
        first_select = first.select[0]
        assert isinstance(first_select, ast.Constant)
        self.assertEqual(first_select.value, 1)

        second = parse_select(sql, placeholders={"x": ast.Constant(value=99), "n": ast.Constant(value=50)})
        self.assertEqual(_builtin_parse_cache.currsize + _user_parse_cache.currsize, 1)
        assert isinstance(second, ast.SelectQuery)
        second_select = second.select[0]
        assert isinstance(second_select, ast.Constant)
        self.assertEqual(second_select.value, 99)

    def test_returned_ast_has_independent_nested_objects(self):
        # deepcopy must reach nested children — mutating a deep field must
        # not leak to the cached entry.
        sql = "SELECT count() FROM events WHERE event = '$pageview' -- nested mutation"
        first = parse_select(sql)
        assert isinstance(first, ast.SelectQuery) and first.where is not None
        first.where = ast.Constant(value=False)
        second = parse_select(sql)
        assert isinstance(second, ast.SelectQuery) and second.where is not None
        self.assertNotEqual(second.where, ast.Constant(value=False))
        # Cache must have served the second call; otherwise this only proves
        # that a fresh parse produces a fresh AST, which is uninteresting.
        self.assertEqual(self._total_cache_size(), 1)

    def test_parse_expr_cached_separately_by_start_arg(self):
        # `parse_expr` short identifier-only inputs route to user cache via
        # the interning guard; use explicit BUILTIN to test start-arg keying
        # in isolation.
        expr = "1 + 1 -- start-arg keying test, long enough to cache"
        parse_expr(expr, start=0, cache_origin=CacheOrigin.BUILTIN)
        parse_expr(expr, start=1, cache_origin=CacheOrigin.BUILTIN)
        self.assertEqual(_builtin_parse_cache.currsize, 2)

    def test_looks_like_code_literal_finds_function_literal(self):
        s = "this is a literal in this function — definitely past the min length"
        self.assertTrue(_looks_like_code_literal(s))

    def test_looks_like_code_literal_rejects_constructed_strings(self):
        # `.join` produces a fresh runtime string (compile-time concat would
        # be folded into a single literal).
        s = " ".join(["constructed", "string", "definitely", "long", "enough", "now"])
        self.assertFalse(_looks_like_code_literal(s))

    def test_looks_like_code_literal_rejects_short_strings(self):
        # Short identifier-shaped strings may be process-wide-interned by
        # CPython and falsely identity-match `co_consts` elsewhere.
        s = "event"
        self.assertFalse(_looks_like_code_literal(s))

    def test_cache_origin_typo_raises(self):
        with self.assertRaises(ValueError):
            parse_select("SELECT 1", cache_origin="buultin")  # type: ignore[arg-type]

    @parameterized.expand([(CacheOrigin.AUTO,), (CacheOrigin.USER,)])
    def test_oversized_query_skips_user_and_auto_caches(self, origin):
        padding = "x" * (_MAX_CACHEABLE_STATEMENT_LEN + 1)
        sql = f"SELECT 1 -- {padding}"
        parse_select(sql, cache_origin=origin)
        self.assertEqual(_builtin_parse_cache.currsize, 0)
        self.assertEqual(_user_parse_cache.currsize, 0)

    @parameterized.expand([(CacheOrigin.AUTO,), (CacheOrigin.USER,), (CacheOrigin.BUILTIN,)])
    def test_undersized_query_skips_cache(self, origin):
        # Short queries skip caching regardless of origin — even explicit
        # BUILTIN doesn't bypass the minimum, since the speedup isn't worth
        # the slot.
        sql = "SELECT 1"
        assert len(sql) < _MIN_CACHEABLE_STATEMENT_LEN
        parse_select(sql, cache_origin=origin)
        self.assertEqual(_builtin_parse_cache.currsize, 0)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_oversized_query_still_caches_under_explicit_builtin(self):
        # Explicit BUILTIN bypasses the upper bound (trusted opt-in for
        # large queries).
        padding = "x" * (_MAX_CACHEABLE_STATEMENT_LEN + 1)
        sql = f"SELECT 1 -- {padding}"
        parse_select(sql, cache_origin=CacheOrigin.BUILTIN)
        self.assertEqual(_builtin_parse_cache.currsize, 1)

    def test_parse_string_template_literal_routes_to_builtin(self):
        # The cache key is `"F'" + string` (runtime concat) so naive
        # auto-detect would never see a built-in literal here — we
        # classify against the raw `string` arg instead.
        parse_string_template("hello {x} world, this is a long enough template now")
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_syntax_errors_are_not_cached(self):
        # SQL has to clear `_MIN_CACHEABLE_STATEMENT_LEN`; otherwise the
        # length gate masks the error-path skip we're trying to verify.
        with self.assertRaises(BaseHogQLError):
            parse_select(
                "NOT VALID SQL -- padding to exceed the minimum cacheable length",
                cache_origin=CacheOrigin.USER,
            )
        self.assertEqual(_user_parse_cache.currsize, 0)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    @parameterized.expand(
        [
            (CacheOrigin.BUILTIN, "SELECT 4 -- prior built-in cache entry, plenty long enough"),
            (CacheOrigin.USER, "SELECT 5 -- prior user cache entry, also plenty long enough"),
        ]
    )
    def test_auto_path_skips_frame_walk_on_hit(self, prior_origin, sql):
        parse_select(sql, cache_origin=prior_origin)
        with patch("posthog.hogql.parser._looks_like_code_literal") as detector:
            parse_select(sql)
            detector.assert_not_called()

    @parameterized.expand(
        [
            (CacheOrigin.BUILTIN, "hello {x} world, prior built-in template entry, long enough"),
            (CacheOrigin.USER, "hello {x} world, prior user template entry, also long enough"),
        ]
    )
    def test_parse_string_template_skips_frame_walk_on_hit(self, prior_origin, template):
        # The cache key is the runtime-concatenated `"F'" + template`, but
        # the classifier must still run only on the cold path — otherwise
        # warm template hits pay the 40-frame walk every call.
        parse_string_template(template, cache_origin=prior_origin)
        with patch("posthog.hogql.parser._looks_like_code_literal") as detector:
            parse_string_template(template)
            detector.assert_not_called()
