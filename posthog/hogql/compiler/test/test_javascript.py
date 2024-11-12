from posthog.hogql.compiler.javascript import create_javascript, to_js_expr, to_js_program
from posthog.hogql.errors import NotImplementedError, QueryError
from posthog.hogql.parser import parse_program
from posthog.test.base import BaseTest


class TestJavaScript(BaseTest):
    def test_javascript_create(self):
        self.assertEqual(to_js_expr("1 + 2"), "(1 + 2)")
        self.assertEqual(to_js_expr("1 and 2"), "(1 && 2)")
        self.assertEqual(to_js_expr("1 or 2"), "(1 || 2)")
        self.assertEqual(to_js_expr("1 or (2 and 1) or 2"), "(1 || (2 && 1) || 2)")
        self.assertEqual(to_js_expr("(1 or 2) and (1 or 2)"), "((1 || 2) && (1 || 2))")
        self.assertEqual(to_js_expr("not true"), "(!true)")
        self.assertEqual(to_js_expr("true"), "true")
        self.assertEqual(to_js_expr("false"), "false")
        self.assertEqual(to_js_expr("null"), "null")
        self.assertEqual(to_js_expr("3.14"), "3.14")
        self.assertEqual(to_js_expr("properties.bla"), "properties.bla")
        self.assertEqual(to_js_expr("concat('arg', 'another')"), '(String("arg") + String("another"))')
        self.assertEqual(to_js_expr("ifNull(properties.email, false)"), "(properties.email ?? false)")
        self.assertEqual(to_js_expr("1 = 2"), "(1 == 2)")
        self.assertEqual(to_js_expr("1 == 2"), "(1 == 2)")
        self.assertEqual(to_js_expr("1 != 2"), "(1 != 2)")
        self.assertEqual(to_js_expr("1 < 2"), "(1 < 2)")
        self.assertEqual(to_js_expr("1 <= 2"), "(1 <= 2)")
        self.assertEqual(to_js_expr("1 > 2"), "(1 > 2)")
        self.assertEqual(to_js_expr("1 >= 2"), "(1 >= 2)")
        self.assertEqual(to_js_expr("1 in 2"), "(2.includes(1))")
        self.assertEqual(to_js_expr("1 not in 2"), "(!2.includes(1))")
        self.assertEqual(to_js_expr("match('test', 'e.*')"), 'match("test", "e.*")')
        self.assertEqual(to_js_expr("not('test')"), '(!"test")')
        self.assertEqual(to_js_expr("or('test', 'test2')"), '("test" || "test2")')
        self.assertEqual(to_js_expr("and('test', 'test2')"), '("test" && "test2")')

    def test_javascript_create_not_implemented_error(self):
        with self.assertRaises(NotImplementedError) as e:
            to_js_expr("(select 1)")
        self.assertEqual(str(e.exception), "JavaScriptCompiler has no method visit_select_query")

    def test_javascript_create_query_error(self):
        with self.assertRaises(QueryError) as e:
            to_js_expr("1 in cohort 2")
        assert "Unsupported comparison operator: in cohort" in str(e.exception)

        # with self.assertRaises(QueryError) as e:
        #     to_js_program("globalVar := 1")
        # self.assertEqual(
        #     str(e.exception), 'Variable `globalVar` already declared in this scope'
        # )

        # with self.assertRaises(QueryError) as e:
        #     to_js_program("globalVar.properties.bla := 1")
        # self.assertEqual(
        #     str(e.exception), 'Variable `globalVar` already declared in this scope'
        # )

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

    def test_javascript_in_repl(self):
        code = create_javascript(parse_program("let a:=1"), in_repl=False).code
        self.assertEqual(code.strip(), "let a = 1;")

        code = create_javascript(parse_program("let a:=1"), in_repl=True).code
        self.assertEqual(code.strip(), "let a = 1;")

    def test_javascript_hogqlx(self):
        code = to_js_expr("<Sparkline data={[1,2,3]} />")
        expected_code = "<Sparkline data={[ 1, 2, 3 ]} />"
        self.assertEqual(code.strip(), expected_code.strip())
