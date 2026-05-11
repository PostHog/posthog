from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import (
    CacheOrigin,
    _builtin_parse_cache,
    _looks_like_code_literal,
    _user_parse_cache,
    clear_parse_caches,
    parse_expr,
    parse_select,
)


class TestParserCache(BaseTest):
    def setUp(self):
        super().setUp()
        clear_parse_caches()

    def test_cache_hit_returns_equivalent_ast(self):
        sql = "SELECT count() FROM events"
        first = parse_select(sql)
        second = parse_select(sql)
        self.assertEqual(first, second)

    def test_cache_hit_returns_distinct_object(self):
        # The resolver and printer mutate the AST in place — cache hits must
        # not share node identity with previous returns or each other.
        sql = "SELECT count() FROM events"
        first = parse_select(sql)
        second = parse_select(sql)
        self.assertIsNot(first, second)

    def test_mutation_does_not_leak_across_calls(self):
        sql = "SELECT 1"
        first = parse_select(sql)
        assert isinstance(first, ast.SelectQuery)
        first.limit = ast.Constant(value=10)
        second = parse_select(sql)
        assert isinstance(second, ast.SelectQuery)
        self.assertIsNone(second.limit)

    @parameterized.expand(
        [
            (CacheOrigin.BUILTIN, lambda: _builtin_parse_cache, lambda: _user_parse_cache),
            (CacheOrigin.USER, lambda: _user_parse_cache, lambda: _builtin_parse_cache),
        ]
    )
    def test_explicit_origin_routes_to_matching_cache(self, origin, target_getter, other_getter):
        parse_select(f"SELECT 1 -- routing test {origin}", cache_origin=origin)
        self.assertEqual(target_getter().currsize, 1)
        self.assertEqual(other_getter().currsize, 0)

    def test_auto_detects_function_local_literal(self):
        # Literal must be long enough to bypass the auto-interning guard
        # (`_LITERAL_DETECTION_MIN_LEN`). Real production HogQL queries are
        # well past 32 chars.
        parse_select("SELECT count() FROM events WHERE event = '$exception'")
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_auto_routes_constructed_strings_to_user_cache(self):
        # `.join` produces a fresh string object that isn't in any frame's
        # co_consts (constant string concat like `"a " + "b"` would be folded
        # at compile time into a single literal and incorrectly look built-in).
        sql = " ".join(["SELECT", "count()", "FROM", "events", "WHERE", "event", "=", "'$pageview'"])
        parse_select(sql)
        self.assertEqual(_user_parse_cache.currsize, 1)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    def test_auto_short_strings_route_to_user_cache(self):
        # Short identifier-shaped strings can be auto-interned by CPython and
        # spuriously identity-match `co_consts` elsewhere. The min-length
        # guard sends them to the user cache regardless.
        parse_expr("count()")
        self.assertEqual(_user_parse_cache.currsize, 1)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    def test_user_pollution_does_not_displace_builtin(self):
        # Fill the built-in cache with one entry, then flood the user cache.
        parse_select("SELECT 'builtin entry'", cache_origin=CacheOrigin.BUILTIN)
        user_maxsize = int(_user_parse_cache.maxsize)
        for i in range(user_maxsize + 50):
            parse_select(f"SELECT {i}", cache_origin=CacheOrigin.USER)
        # Built-in cache still has its entry; user cache is at maxsize.
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, user_maxsize)

    def test_placeholders_still_substitute_after_cache_hit(self):
        sql = "SELECT {x}"
        placeholders: dict[str, ast.Expr] = {"x": ast.Constant(value=42)}
        # Warm the cache without placeholders.
        parse_select(sql)
        # Second call with placeholders must produce the substituted AST.
        node = parse_select(sql, placeholders=placeholders)
        assert isinstance(node, ast.SelectQuery)
        self.assertEqual(len(node.select), 1)
        substituted = node.select[0]
        assert isinstance(substituted, ast.Constant)
        self.assertEqual(substituted.value, 42)

    def test_returned_ast_has_independent_nested_objects(self):
        # deepcopy must reach nested children — mutating a deep field must
        # not leak to the cached entry. Pick a query with nested structure.
        sql = "SELECT count() FROM events WHERE event = '$pageview'"
        first = parse_select(sql)
        assert isinstance(first, ast.SelectQuery) and first.where is not None
        # Replace a deeply nested field
        first.where = ast.Constant(value=False)
        second = parse_select(sql)
        assert isinstance(second, ast.SelectQuery) and second.where is not None
        # The cached entry was untouched
        self.assertNotEqual(second.where, ast.Constant(value=False))

    def test_parse_expr_cached_separately_by_start_arg(self):
        # Two different start values must produce two different cache entries.
        # `parse_expr` short identifier-only inputs go to user cache (interning
        # guard); use explicit BUILTIN to test the start-arg keying.
        parse_expr("1 + 1", start=0, cache_origin=CacheOrigin.BUILTIN)
        parse_expr("1 + 1", start=1, cache_origin=CacheOrigin.BUILTIN)
        self.assertEqual(_builtin_parse_cache.currsize, 2)

    def test_looks_like_code_literal_finds_function_literal(self):
        s = "this is a literal in this function — definitely past the min length"
        self.assertTrue(_looks_like_code_literal(s))

    def test_looks_like_code_literal_rejects_constructed_strings(self):
        # `.join` produces a fresh runtime string (concat of two literals would
        # be folded at compile time and incorrectly look like a literal). Use
        # enough parts to clear the min-length guard.
        s = " ".join(["constructed", "string", "definitely", "long", "enough", "now"])
        self.assertFalse(_looks_like_code_literal(s))

    def test_looks_like_code_literal_rejects_short_strings(self):
        # Short literals are rejected up-front because Python auto-interns
        # short identifier-shaped strings — user input may share identity
        # with `co_consts` entries elsewhere.
        s = "event"  # literal in this function, but too short
        self.assertFalse(_looks_like_code_literal(s))

    def test_cache_origin_typo_raises(self):
        # A misspelled origin must raise rather than silently routing to the
        # user cache via `==` else-branch.
        with self.assertRaises(ValueError):
            parse_select("SELECT 1", cache_origin="buultin")  # type: ignore[arg-type]

    @parameterized.expand(
        [
            (CacheOrigin.AUTO,),
            (CacheOrigin.USER,),
        ]
    )
    def test_oversized_query_skips_user_and_auto_caches(self, origin):
        # An attacker-controlled HogQL query larger than the size cap must
        # NOT enter the cache — bounds worst-case memory growth.
        from posthog.hogql.parser import _MAX_CACHEABLE_STATEMENT_LEN

        # Build a syntactically valid query over the size limit. Use a long
        # comment so we don't blow up parse time on something pathological.
        padding = "x" * (_MAX_CACHEABLE_STATEMENT_LEN + 1)
        sql = f"SELECT 1 -- {padding}"
        parse_select(sql, cache_origin=origin)
        self.assertEqual(_builtin_parse_cache.currsize, 0)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_oversized_query_still_caches_under_explicit_builtin(self):
        # Explicit BUILTIN is opt-in by code that knows what it's storing —
        # the size cap doesn't apply.
        from posthog.hogql.parser import _MAX_CACHEABLE_STATEMENT_LEN

        padding = "x" * (_MAX_CACHEABLE_STATEMENT_LEN + 1)
        sql = f"SELECT 1 -- {padding}"
        parse_select(sql, cache_origin=CacheOrigin.BUILTIN)
        self.assertEqual(_builtin_parse_cache.currsize, 1)

    def test_parse_string_template_literal_routes_to_builtin(self):
        # Template strings used to always land in the user cache because the
        # key is `"F'" + string` (runtime concat). Auto-detect now classifies
        # against the raw `string` first.
        from posthog.hogql.parser import parse_string_template

        parse_string_template("hello {x} world, this is a long enough template now")
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_syntax_errors_are_not_cached(self):
        from posthog.hogql.errors import BaseHogQLError

        with self.assertRaises(BaseHogQLError):
            parse_select("NOT VALID SQL", cache_origin=CacheOrigin.USER)
        # The failed parse shouldn't have populated either cache.
        self.assertEqual(_user_parse_cache.currsize, 0)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    @parameterized.expand(
        [
            (CacheOrigin.BUILTIN, "SELECT 4 -- prior built-in cache entry, plenty long enough"),
            (CacheOrigin.USER, "SELECT 5 -- prior user cache entry, also plenty long enough"),
        ]
    )
    def test_auto_path_skips_frame_walk_on_hit(self, prior_origin, sql):
        # The whole point of the fast path: when an entry exists in either
        # cache, _looks_like_code_literal should not be invoked.
        parse_select(sql, cache_origin=prior_origin)
        with patch("posthog.hogql.parser._looks_like_code_literal") as detector:
            parse_select(sql)  # cache_origin defaults to AUTO
            detector.assert_not_called()
