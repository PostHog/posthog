from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.compiler.javascript import JavaScriptCompiler, Local, _sanitize_identifier, to_js_expr, to_js_program
from posthog.hogql.errors import QueryError


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
        self.assertEqual(to_js_expr("1 + 2"), "(1 + 2)")
        self.assertEqual(to_js_expr("1 and 2"), "!!(1 && 2)")
        self.assertEqual(to_js_expr("1 or 2"), "!!(1 || 2)")
        self.assertEqual(to_js_expr("not true"), "(!true)")
        self.assertEqual(to_js_expr("1 < 2"), "(1 < 2)")
        self.assertEqual(to_js_expr("properties.bla"), '__getProperty(__getGlobal("properties"), "bla", true)')

    def test_javascript_string_functions(self):
        self.assertEqual(to_js_expr("concat('a', 'b')"), 'concat("a", "b")')
        self.assertEqual(to_js_expr("lower('HELLO')"), 'lower("HELLO")')
        self.assertEqual(to_js_expr("upper('hello')"), 'upper("hello")')
        self.assertEqual(to_js_expr("reverse('abc')"), 'reverse("abc")')

    def test_arithmetic_operations(self):
        self.assertEqual(to_js_expr("3 - 1"), "(3 - 1)")
        self.assertEqual(to_js_expr("2 * 3"), "(2 * 3)")
        self.assertEqual(to_js_expr("5 / 2"), "(5 / 2)")
        self.assertEqual(to_js_expr("10 % 3"), "(10 % 3)")

    def test_comparison_operations(self):
        self.assertEqual(to_js_expr("3 = 4"), "(3 == 4)")
        self.assertEqual(to_js_expr("3 != 4"), "(3 != 4)")
        self.assertEqual(to_js_expr("3 < 4"), "(3 < 4)")
        self.assertEqual(to_js_expr("3 <= 4"), "(3 <= 4)")
        self.assertEqual(to_js_expr("3 > 4"), "(3 > 4)")
        self.assertEqual(to_js_expr("3 >= 4"), "(3 >= 4)")

    def test_javascript_create_query_error(self):
        with self.assertRaises(QueryError) as e:
            to_js_expr("1 in cohort 2")
        self.assertIn(
            "Can't use cohorts in real-time filters. Please inline the relevant expressions", str(e.exception)
        )

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
        expected_code = "if ((1 < 2)) {\n    return true;\n} else {\n    return false;\n}"
        self.assertEqual(code.strip(), expected_code.strip())

    def test_declare_local(self):
        compiler = JavaScriptCompiler()
        compiler._declare_local("a_var")
        self.assertIn("a_var", [local.name for local in compiler.locals])

    def test_visit_return_statement(self):
        compiler = JavaScriptCompiler()
        code = compiler.visit_return_statement(ast.ReturnStatement(expr=ast.Constant(value="test")))
        self.assertEqual(code, 'return "test";')

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
        self.assertTrue(code.startswith("__lambda((x) => (x + 1))"))

    def test_stl_code(self):
        compiler = JavaScriptCompiler()
        compiler.stl_functions.add("concat")
        stl_code = compiler.get_stl_code()
        self.assertIn("function concat", stl_code)

    def test_sanitize_keywords(self):
        self.assertEqual(_sanitize_identifier("for"), "__x_for")
        self.assertEqual(_sanitize_identifier("await"), "__x_await")

    def test_json_parse(self):
        code = to_js_expr('jsonParse(\'{"key": "value"}\')')
        self.assertEqual(code, 'jsonParse("{\\"key\\": \\"value\\"}")')

    def test_javascript_create_2(self):
        self.assertEqual(to_js_expr("1 + 2"), "(1 + 2)")
        self.assertEqual(to_js_expr("1 and 2"), "!!(1 && 2)")
        self.assertEqual(to_js_expr("1 or 2"), "!!(1 || 2)")
        self.assertEqual(to_js_expr("1 or (2 and 1) or 2"), "!!(1 || !!(2 && 1) || 2)")
        self.assertEqual(to_js_expr("(1 or 2) and (1 or 2)"), "!!(!!(1 || 2) && !!(1 || 2))")
        self.assertEqual(to_js_expr("not true"), "(!true)")
        self.assertEqual(to_js_expr("true"), "true")
        self.assertEqual(to_js_expr("false"), "false")
        self.assertEqual(to_js_expr("null"), "null")
        self.assertEqual(to_js_expr("3.14"), "3.14")
        self.assertEqual(to_js_expr("properties.bla"), '__getProperty(__getGlobal("properties"), "bla", true)')
        self.assertEqual(to_js_expr("concat('arg', 'another')"), 'concat("arg", "another")')
        self.assertEqual(
            to_js_expr("ifNull(properties.email, false)"),
            '(__getProperty(__getGlobal("properties"), "email", true) ?? false)',
        )
        self.assertEqual(to_js_expr("1 in 2"), "(2.includes(1))")
        self.assertEqual(to_js_expr("1 not in 2"), "(!2.includes(1))")
        self.assertEqual(to_js_expr("match('test', 'e.*')"), 'match("test", "e.*")')
        self.assertEqual(to_js_expr("not('test')"), '(!"test")')
        self.assertEqual(to_js_expr("or('test', 'test2')"), '!!("test" || "test2")')
        self.assertEqual(to_js_expr("and('test', 'test2')"), '!!("test" && "test2")')

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
return fibonacci(6);"""
        self.assertEqual(js_code.strip(), expected_js.strip())

    def test_javascript_hogqlx(self):
        code = to_js_expr("<Sparkline data={[1,2,3]} />")
        self.assertEqual(code.strip(), '{"__hx_tag": "Sparkline", "data": [1, 2, 3]}')

    def test_sanitized_function_names(self):
        code = to_js_expr("typeof('test')")
        self.assertEqual(code, '__x_typeof("test")')

    def test_function_name_sanitization(self):
        code = to_js_expr("Error('An error occurred')")
        self.assertEqual(code, '__x_Error("An error occurred")')

    def test_ilike(self):
        code = to_js_expr("'hello' ilike '%ELLO%'")
        self.assertEqual(code, 'ilike("hello", "%ELLO%")')

    def test_not_ilike(self):
        code = to_js_expr("'hello' not ilike '%ELLO%'")
        self.assertEqual(code, '!ilike("hello", "%ELLO%")')

    def test_regex(self):
        code = to_js_expr("'hello' =~ 'h.*o'")
        self.assertEqual(code, 'match("hello", "h.*o")')

    def test_not_regex(self):
        code = to_js_expr("'hello' !~ 'h.*o'")
        self.assertEqual(code, '!match("hello", "h.*o")')

    def test_i_regex(self):
        code = to_js_expr("'hello' =~* 'H.*O'")
        self.assertEqual(code, '__imatch("hello", "H.*O")')

    def test_not_i_regex(self):
        code = to_js_expr("'hello' !~* 'H.*O'")
        self.assertEqual(code, '!__imatch("hello", "H.*O")')

    def test_array_access(self):
        code = to_js_expr("array[2]")
        self.assertEqual(code, '__getProperty(__getGlobal("array"), 2, false)')

    def test_tuple_access(self):
        code = to_js_expr("(1, 2, 3).2")
        self.assertEqual(code, "__getProperty(tuple(1, 2, 3), 2, false)")

    def test_between_expr(self):
        code = to_js_expr("properties.value between 1 and 10")
        self.assertIn("expr >= 1 && expr <= 10", code)
        self.assertEqual(code.count("__getProperty"), 1)

    def test_function_assignment_error(self):
        compiler = JavaScriptCompiler()
        with self.assertRaises(QueryError) as context:
            compiler.visit_variable_assignment(
                ast.VariableAssignment(left=ast.Field(chain=["globalVar"]), right=ast.Constant(value=42))
            )
        self.assertIn(
            'Variable "globalVar" not declared in this scope. Cannot assign to globals.', str(context.exception)
        )

    def test_bytecode_sql(self):
        self.assertEqual(
            to_js_expr("sql(1 + 1)"),
            '{"__hx_ast": "ArithmeticOperation", "left": {"__hx_ast": "Constant", "value": 1}, "right": {"__hx_ast": "Constant", "value": 1}, "op": "+"}',
        )

    def test_bytecode_sql_select(self):
        self.assertEqual(
            to_js_expr("(select 1)"),
            '{"__hx_ast": "SelectQuery", "select": [{"__hx_ast": "Constant", "value": 1}]}',
        )

        self.assertEqual(
            to_js_expr("(select b.* from b join a on a.id = b.id)"),
            '{"__hx_ast": "SelectQuery", "select": [{"__hx_ast": "Field", "chain": ["b", "*"], "from_asterisk": false}], "select_from": {"__hx_ast": "JoinExpr", '
            '"table": {"__hx_ast": "Field", "chain": ["b"], "from_asterisk": false}, "next_join": {"__hx_ast": "JoinExpr", "join_type": "JOIN", "table": '
            '{"__hx_ast": "Field", "chain": ["a"], "from_asterisk": false}, "constraint": {"__hx_ast": "JoinConstraint", "expr": {"__hx_ast": "CompareOperation", '
            '"left": {"__hx_ast": "Field", "chain": ["a", "id"], "from_asterisk": false}, "right": {"__hx_ast": "Field", "chain": ["b", "id"], "from_asterisk": false}, "op": "=="}, '
            '"constraint_type": "ON"}}}}',
        )

    def test_lambda_dict_literal(self):
        code = to_js_expr("x -> {'key': x}")
        assert code == '__lambda((x) => ({"key": x}))'
