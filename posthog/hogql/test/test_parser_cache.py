from posthog.test.base import BaseTest
from unittest.mock import patch

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

    def test_user_origin_routes_to_user_cache(self):
        parse_select("SELECT 1", cache_origin=CacheOrigin.USER)
        self.assertEqual(_user_parse_cache.currsize, 1)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    def test_builtin_origin_routes_to_builtin_cache(self):
        parse_select("SELECT 2", cache_origin=CacheOrigin.BUILTIN)
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_auto_detects_function_local_literal(self):
        # "SELECT 3" is a literal in this test function's compiled code — should
        # land in the built-in cache via the frame-walk detector.
        parse_select("SELECT 3")
        self.assertEqual(_builtin_parse_cache.currsize, 1)
        self.assertEqual(_user_parse_cache.currsize, 0)

    def test_auto_routes_constructed_strings_to_user_cache(self):
        # `.join` produces a fresh string object that isn't in any frame's
        # co_consts (constant string concat like `"a " + "b"` would be folded
        # at compile time into a single literal and incorrectly look built-in).
        sql = " ".join(["SELECT", "count()", "FROM", "events"])
        parse_select(sql)
        self.assertEqual(_user_parse_cache.currsize, 1)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    def test_user_pollution_does_not_displace_builtin(self):
        # Fill the built-in cache with one entry, then flood the user cache.
        parse_select("SELECT 'builtin entry'", cache_origin=CacheOrigin.BUILTIN)
        user_maxsize = _user_parse_cache.maxsize
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
        parse_expr("1 + 1", start=0)
        parse_expr("1 + 1", start=1)
        self.assertEqual(_builtin_parse_cache.currsize, 2)

    def test_looks_like_code_literal_finds_function_literal(self):
        s = "this is a literal in this function"
        self.assertTrue(_looks_like_code_literal(s))

    def test_looks_like_code_literal_rejects_constructed_strings(self):
        # `.join` produces a fresh runtime string (concat of two literals would
        # be folded at compile time and incorrectly look like a literal).
        s = " ".join(["constructed", "string"])
        self.assertFalse(_looks_like_code_literal(s))

    def test_syntax_errors_are_not_cached(self):
        from posthog.hogql.errors import BaseHogQLError

        with self.assertRaises(BaseHogQLError):
            parse_select("NOT VALID SQL", cache_origin=CacheOrigin.USER)
        # The failed parse shouldn't have populated either cache.
        self.assertEqual(_user_parse_cache.currsize, 0)
        self.assertEqual(_builtin_parse_cache.currsize, 0)

    def test_auto_path_skips_frame_walk_on_hit(self):
        # The whole point of the fast path: when an entry exists in either
        # cache, _looks_like_code_literal should not be invoked.
        parse_select("SELECT 4", cache_origin=CacheOrigin.BUILTIN)
        with patch("posthog.hogql.parser._looks_like_code_literal") as detector:
            parse_select("SELECT 4")  # cache_origin defaults to AUTO
            detector.assert_not_called()

    def test_auto_path_serves_from_user_cache_without_classifying(self):
        # An entry previously stashed in the user cache should also be served
        # without invoking the frame walk.
        parse_select(" ".join(["SELECT", "5"]), cache_origin=CacheOrigin.USER)
        with patch("posthog.hogql.parser._looks_like_code_literal") as detector:
            # Reconstruct the same statement at runtime (so it'd be classified
            # as user if we did walk the stack — we should hit the user cache
            # without needing to.).
            parse_select(" ".join(["SELECT", "5"]))
            detector.assert_not_called()
