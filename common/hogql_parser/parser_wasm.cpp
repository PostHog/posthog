// parser_wasm.cpp - WebAssembly Bindings for HogQL Parser
// This file provides JavaScript/WASM bindings for the core parser (parser_core.cpp).
// It exports functions that can be called from JavaScript.

#include <emscripten/bind.h>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "string.h"
#include "json_builder.h"

using namespace std;
using namespace emscripten;

// Include the core parser implementation
#include "parser_core.cpp"

// ERROR HANDLING FOR WASM

class HogQLErrorListener : public antlr4::BaseErrorListener {
 public:
  string input;

  HogQLErrorListener(string input) : input(input) {}

  void syntaxError(
      antlr4::Recognizer* recognizer,
      antlr4::Token* offendingSymbol,
      size_t line,
      size_t charPositionInLine,
      const string& msg,
      exception_ptr e
  ) override {
    size_t start = getPosition(line, charPositionInLine);
    if (start == string::npos) {
      start = 0;
    }
    throw SyntaxError(msg, start, input.size());
  }

 private:
  size_t getPosition(size_t line, size_t column) {
    size_t linePosition = 0;
    for (size_t i = 0; i < line - 1; i++) {
      size_t endOfLine = input.find("\n", linePosition);
      if (endOfLine == string::npos) {
        return string::npos;
      }
      linePosition = endOfLine + 1;
    }
    return linePosition + column;
  }
};

// Helper function to build JSON error
string buildWASMError(const char* error_type, const string& message, size_t start, size_t end) {
  JSONBuilder json;
  json.startObject();
  json.addKey("error"); json.addBool(true);
  json.addKey("type"); json.addString(error_type);
  json.addKey("message"); json.addString(message);
  json.addPosition("start", {0, 0, start});
  json.addPosition("end", {0, 0, end});
  json.endObject();
  return json.toString();
}

// WASM EXPORTED FUNCTIONS

/**
 * Parse a HogQL expression and return JSON AST.
 *
 * @param input The HogQL expression string
 * @param is_internal If true, omit position information
 * @return JSON string representing the AST or error
 */
string parse_expr(const string& input, bool is_internal = false) {
  try {
    auto input_stream = new antlr4::ANTLRInputStream(input.c_str(), input.length());
    auto lexer = new HogQLLexer(input_stream);
    auto stream = new antlr4::CommonTokenStream(lexer);
    auto parser = new HogQLParser(stream);
    parser->removeErrorListeners();
    auto error_listener = new HogQLErrorListener(input);
    parser->addErrorListener(error_listener);

    HogQLParser::ExprContext* parse_tree;
    try {
      parse_tree = parser->expr();
    } catch (const antlr4::EmptyStackException &e) {
      delete error_listener; delete parser; delete stream; delete lexer; delete input_stream;
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeConverter converter = HogQLParseTreeConverter(is_internal);
    string result_json = converter.visitAsJSONFinal(parse_tree);

    delete error_listener;
    delete parser;
    delete stream;
    delete lexer;
    delete input_stream;

    return result_json;
  } catch (const SyntaxError& e) {
    return buildWASMError("SyntaxError", e.what(), e.start, e.end);
  } catch (const NotImplementedError& e) {
    return buildWASMError("NotImplementedError", e.what(), e.start, e.end);
  } catch (const ParsingError& e) {
    return buildWASMError("ParsingError", e.what(), 0, input.size());
  } catch (...) {
    return buildWASMError("ParsingError", "Unexpected exception in parser", 0, input.size());
  }
}

/**
 * Parse an ORDER BY expression and return JSON AST.
 */
string parse_order_expr(const string& input, bool is_internal = false) {
  try {
    auto input_stream = new antlr4::ANTLRInputStream(input.c_str(), input.length());
    auto lexer = new HogQLLexer(input_stream);
    auto stream = new antlr4::CommonTokenStream(lexer);
    auto parser = new HogQLParser(stream);
    parser->removeErrorListeners();
    auto error_listener = new HogQLErrorListener(input);
    parser->addErrorListener(error_listener);

    HogQLParser::OrderExprContext* parse_tree;
    try {
      parse_tree = parser->orderExpr();
    } catch (const antlr4::EmptyStackException &e) {
      delete error_listener; delete parser; delete stream; delete lexer; delete input_stream;
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeConverter converter = HogQLParseTreeConverter(is_internal);
    string result_json = converter.visitAsJSONFinal(parse_tree);

    delete error_listener;
    delete parser;
    delete stream;
    delete lexer;
    delete input_stream;

    return result_json;
  } catch (const SyntaxError& e) {
    return buildWASMError("SyntaxError", e.what(), e.start, e.end);
  } catch (...) {
    return buildWASMError("ParsingError", "Unexpected exception in parser", 0, input.size());
  }
}

/**
 * Parse a SELECT statement and return JSON AST.
 */
string parse_select(const string& input, bool is_internal = false) {
  try {
    auto input_stream = new antlr4::ANTLRInputStream(input.c_str(), input.length());
    auto lexer = new HogQLLexer(input_stream);
    auto stream = new antlr4::CommonTokenStream(lexer);
    auto parser = new HogQLParser(stream);
    parser->removeErrorListeners();
    auto error_listener = new HogQLErrorListener(input);
    parser->addErrorListener(error_listener);

    HogQLParser::SelectContext* parse_tree;
    try {
      parse_tree = parser->select();
    } catch (const antlr4::EmptyStackException &e) {
      delete error_listener; delete parser; delete stream; delete lexer; delete input_stream;
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeConverter converter = HogQLParseTreeConverter(is_internal);
    string result_json = converter.visitAsJSONFinal(parse_tree);

    delete error_listener;
    delete parser;
    delete stream;
    delete lexer;
    delete input_stream;

    return result_json;
  } catch (const SyntaxError& e) {
    return buildWASMError("SyntaxError", e.what(), e.start, e.end);
  } catch (...) {
    return buildWASMError("ParsingError", "Unexpected exception in parser", 0, input.size());
  }
}

/**
 * Parse a Hog template string and return JSON AST.
 */
string parse_full_template_string(const string& input, bool is_internal = false) {
  try {
    auto input_stream = new antlr4::ANTLRInputStream(input.c_str(), input.length());
    auto lexer = new HogQLLexer(input_stream);
    auto stream = new antlr4::CommonTokenStream(lexer);
    auto parser = new HogQLParser(stream);
    parser->removeErrorListeners();
    auto error_listener = new HogQLErrorListener(input);
    parser->addErrorListener(error_listener);

    HogQLParser::FullTemplateStringContext* parse_tree;
    try {
      parse_tree = parser->fullTemplateString();
    } catch (const antlr4::EmptyStackException &e) {
      delete error_listener; delete parser; delete stream; delete lexer; delete input_stream;
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeConverter converter = HogQLParseTreeConverter(is_internal);
    string result_json = converter.visitAsJSONFinal(parse_tree);

    delete error_listener;
    delete parser;
    delete stream;
    delete lexer;
    delete input_stream;

    return result_json;
  } catch (const SyntaxError& e) {
    return buildWASMError("SyntaxError", e.what(), e.start, e.end);
  } catch (...) {
    return buildWASMError("ParsingError", "Unexpected exception in parser", 0, input.size());
  }
}

/**
 * Parse a Hog program and return JSON AST.
 */
string parse_program(const string& input, bool is_internal = false) {
  try {
    auto input_stream = new antlr4::ANTLRInputStream(input.c_str(), input.length());
    auto lexer = new HogQLLexer(input_stream);
    auto stream = new antlr4::CommonTokenStream(lexer);
    auto parser = new HogQLParser(stream);
    parser->removeErrorListeners();
    auto error_listener = new HogQLErrorListener(input);
    parser->addErrorListener(error_listener);

    HogQLParser::ProgramContext* parse_tree;
    try {
      parse_tree = parser->program();
    } catch (const antlr4::EmptyStackException &e) {
      delete error_listener; delete parser; delete stream; delete lexer; delete input_stream;
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeConverter converter = HogQLParseTreeConverter(is_internal);
    string result_json = converter.visitAsJSONFinal(parse_tree);

    delete error_listener;
    delete parser;
    delete stream;
    delete lexer;
    delete input_stream;

    return result_json;
  } catch (const SyntaxError& e) {
    return buildWASMError("SyntaxError", e.what(), e.start, e.end);
  } catch (...) {
    return buildWASMError("ParsingError", "Unexpected exception in parser", 0, input.size());
  }
}

/**
 * Unquote a string literal and return the text.
 */
string parse_string_literal_text_wasm(const string& input) {
  try {
    return parse_string_literal_text(input.c_str());
  } catch (const SyntaxError& e) {
    return buildWASMError("SyntaxError", e.what(), e.start, e.end);
  } catch (...) {
    return buildWASMError("ParsingError", "Failed to parse string literal", 0, input.size());
  }
}

// EMSCRIPTEN BINDINGS

EMSCRIPTEN_BINDINGS(hogql_parser) {
  emscripten::function("parseExpr", &parse_expr, emscripten::allow_raw_pointers());
  emscripten::function("parseOrderExpr", &parse_order_expr, emscripten::allow_raw_pointers());
  emscripten::function("parseSelect", &parse_select, emscripten::allow_raw_pointers());
  emscripten::function("parseFullTemplateString", &parse_full_template_string, emscripten::allow_raw_pointers());
  emscripten::function("parseProgram", &parse_program, emscripten::allow_raw_pointers());
  emscripten::function("parseStringLiteralText", &parse_string_literal_text_wasm, emscripten::allow_raw_pointers());
}
