from posthog.hogql.compiler.javascript import JavaScriptCompiler, Local, _sanitize_identifier, to_js_program
from posthog.hogql.errors import NotImplementedError, QueryError
from posthog.hogql import ast
from posthog.test.base import BaseTest


def to_js_expr(expr: str) -> str:
    from posthog.hogql.parser import parse_expr

    return JavaScriptCompiler().visit(parse_expr(expr))


class TestSanitizeIdentifier(BaseTest):
    def test_valid_identifiers(self):
        self.assertEqual(_sanitize_identifier("validName"), "validName")
        self.assertEqual(_sanitize_identifier("_validName123"), "_validName123")

    def test_keywords(self):
        self.assertEqual(_sanitize_identifier("await"), "__x_await")
        self.assertEqual(_sanitize_identifier("class"), "__x_class")

    def test_internal_conflicts(self):
        self.assertEqual(_sanitize_identifier("__x_internal"), "__x___x_internal")

    def test_invalid_identifiers(self):
        self.assertEqual(_sanitize_identifier("123invalid"), '["123invalid"]')
        self.assertEqual(_sanitize_identifier("invalid-name"), '["invalid-name"]')

    def test_integer_identifiers(self):
        self.assertEqual(_sanitize_identifier(123), '["123"]')


class TestJavaScript(BaseTest):
    def test_javascript_create_basic_expressions(self):
        assert to_js_expr("1 + 2") == "(1 + 2)"
        assert to_js_expr("1 and 2") == "!!(1 && 2)"
        assert to_js_expr("1 or 2") == "!!(1 || 2)"
        assert to_js_expr("not true") == "(!true)"
        assert to_js_expr("1 < 2") == "(1 < 2)"
        assert to_js_expr("properties.bla") == '__getProperty(__getGlobal("properties"), "bla", true)'

    def test_javascript_string_functions(self):
        assert to_js_expr("concat('a', 'b')") == 'concat("a", "b")'
        assert to_js_expr("lower('HELLO')") == 'lower("HELLO")'
        assert to_js_expr("upper('hello')") == 'upper("hello")'
        assert to_js_expr("reverse('abc')") == 'reverse("abc")'

    def test_arithmetic_operations(self):
        assert to_js_expr("3 - 1") == "(3 - 1)"
        assert to_js_expr("2 * 3") == "(2 * 3)"
        assert to_js_expr("5 / 2") == "(5 / 2)"
        assert to_js_expr("10 % 3") == "(10 % 3)"

    def test_comparison_operations(self):
        assert to_js_expr("3 = 4") == "(3 == 4)"
        assert to_js_expr("3 != 4") == "(3 != 4)"
        assert to_js_expr("3 < 4") == "(3 < 4)"
        assert to_js_expr("3 <= 4") == "(3 <= 4)"
        assert to_js_expr("3 > 4") == "(3 > 4)"
        assert to_js_expr("3 >= 4") == "(3 >= 4)"

    def test_javascript_create_query_error(self):
        with self.assertRaises(QueryError) as e:
            to_js_expr("1 in cohort 2")
        assert "Can't use cohorts in real-time filters. Please inline the relevant expressions" in str(e.exception)

    def test_scope_errors(self):
        compiler = JavaScriptCompiler(locals=[Local(name="existing_var", depth=0)])
        compiler._start_scope()
        compiler._declare_local("new_var")
        with self.assertRaises(QueryError):
            compiler._declare_local("new_var")
        compiler._end_scope()

    def test_arithmetic_operation(self):
        code = to_js_expr("3 + 5 * (10 / 2) - 7")
        self.assertEqual(code, "((3 + (5 * (10 / 2))) - 7)")

    def test_comparison(self):
        code = to_js_expr("1 in 2")
        self.assertEqual(code, "(2.includes(1))")

    def test_if_else(self):
        code = to_js_program("if (1 < 2) { return true } else { return false }")
        self.assertEqual(code.strip(), "if ((1 < 2)) {\n    return true;\n} else {\n    return false;\n}")

    def test_declare_local(self):
        compiler = JavaScriptCompiler()
        compiler._declare_local("a_var")
        self.assertIn("a_var", [local.name for local in compiler.locals])

    def test_visit_return_statement(self):
        compiler = JavaScriptCompiler()
        code = compiler.visit_return_statement(ast.ReturnStatement(expr=ast.Constant(value="test")))
        self.assertEqual(code, 'return "test";')

    def test_not_implemented_visit_select_query(self):
        with self.assertRaises(NotImplementedError):
            to_js_expr("(select 1)")

    def test_throw_statement(self):
        compiler = JavaScriptCompiler()
        code = compiler.visit_throw_statement(ast.ThrowStatement(expr=ast.Constant(value="Error!")))
        self.assertEqual(code, 'throw "Error!";')

    def test_visit_dict(self):
        code = to_js_expr("{'key1': 'value1', 'key2': 'value2'}")
        self.assertEqual(code, '{"key1": "value1", "key2": "value2"}')

    def test_visit_array(self):
        code = to_js_expr("[1, 2, 3, 4]")
        self.assertEqual(code, "[1, 2, 3, 4]")

    def test_visit_lambda(self):
        code = to_js_expr("x -> x + 1")
        self.assertIn("__lambda", code)
        self.assertTrue(code.startswith("__lambda((x) => (x + 1))"))

    def test_inlined_stl(self):
        compiler = JavaScriptCompiler()
        compiler.inlined_stl.add("concat")
        stl_code = compiler.get_inlined_stl()
        self.assertIn("function concat", stl_code)

    def test_sanitize_keywords(self):
        self.assertEqual(_sanitize_identifier("for"), "__x_for")
        self.assertEqual(_sanitize_identifier("await"), "__x_await")

    def test_json_parse(self):
        code = to_js_expr('jsonParse(\'{"key": "value"}\')')
        self.assertIn("jsonParse", code)

    def test_javascript_create_2(self):
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
