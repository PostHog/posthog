from posthog.hogql.compiler.javascript import JavaScriptCompiler, to_js_program
from posthog.hogql.errors import NotImplementedError, QueryError
from posthog.test.base import BaseTest


def to_js_expr(expr: str) -> str:
    from posthog.hogql.parser import parse_expr

    return JavaScriptCompiler().visit(parse_expr(expr))


class TestJavaScript(BaseTest):
    def test_javascript_create(self):
        assert to_js_expr("1 + 2") == "(1 + 2)"
        assert to_js_expr("1 and 2") == "!!(1 && 2)"
        assert to_js_expr("1 or 2") == "!!(1 || 2)"
        assert to_js_expr("1 or (2 and 1) or 2") == "!!(1 || !!(2 && 1) || 2)"
        assert to_js_expr("(1 or 2) and (1 or 2)") == "!!(!!(1 || 2) && !!(1 || 2))"
        assert to_js_expr("not true") == "(!true)"
        assert to_js_expr("true") == "true"
        assert to_js_expr("false") == "false"
        assert to_js_expr("null") == "null"
        assert to_js_expr("3.14") == "3.14"
        assert to_js_expr("properties.bla") == '__getProperty(__getGlobal("properties"), "bla", true)'
        assert to_js_expr("concat('arg', 'another')"), '(String("arg") + String("another"))'
        assert (
            to_js_expr("ifNull(properties.email, false)")
            == '(__getProperty(__getGlobal("properties"), "email", true) ?? false)'
        )
        assert to_js_expr("1 = 2") == "(1 == 2)"
        assert to_js_expr("1 == 2") == "(1 == 2)"
        assert to_js_expr("1 != 2") == "(1 != 2)"
        assert to_js_expr("1 < 2") == "(1 < 2)"
        assert to_js_expr("1 <= 2") == "(1 <= 2)"
        assert to_js_expr("1 > 2") == "(1 > 2)"
        assert to_js_expr("1 >= 2") == "(1 >= 2)"
        assert to_js_expr("1 in 2") == "(2.includes(1))"
        assert to_js_expr("1 not in 2") == "(!2.includes(1))"
        assert to_js_expr("match('test', 'e.*')") == 'match("test", "e.*")'
        assert to_js_expr("not('test')") == '(!"test")'
        assert to_js_expr("or('test', 'test2')") == '("test" || "test2")'
        assert to_js_expr("and('test', 'test2')") == '("test" && "test2")'

    def test_javascript_create_not_implemented_error(self):
        with self.assertRaises(NotImplementedError) as e:
            to_js_expr("(select 1)")
        self.assertEqual(str(e.exception), "JavaScriptCompiler has no method visit_select_query")

    def test_javascript_create_query_error(self):
        with self.assertRaises(QueryError) as e:
            to_js_expr("1 in cohort 2")
        assert "Can't use cohorts in real-time filters. Please inline the relevant expressions" in str(e.exception)

    def test_javascript_code_generation(self):
        js_code = to_js_program("""
        fun fibonacci(number) {
            if (number < 2) {
                return number;
            } else {
                return fibonacci(number - 1) + fibonacci(number - 2);
            }
        }
        return fibonacci(6);
        """)
        expected_js = """function fibonacci(number) {
    if ((number < 2)) {
            return number;
        } else {
            return (fibonacci((number - 1)) + fibonacci((number - 2)));
        }
}
return fibonacci(6);
"""
        self.assertEqual(js_code.strip(), expected_js.strip())

    def test_javascript_hogqlx(self):
        code = to_js_expr("<Sparkline data={[1,2,3]} />")
        assert code.strip() == '{"__hx_tag": "Sparkline", "data": [1, 2, 3]}'
