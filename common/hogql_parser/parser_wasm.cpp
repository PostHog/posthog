// parser_wasm.cpp - WebAssembly Bindings for HogQL Parser
// This file provides JavaScript/WASM bindings for the core parser (parser_core.cpp).
// It exports functions that can be called from JavaScript.

#include <emscripten/bind.h>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "json.h"
#include "string.h"

using namespace std;
using namespace emscripten;

// Include the core parser implementation
#include "parser_json.cpp"

// ERROR HANDLING FOR WASM

class HogQLErrorListener : public antlr4::BaseErrorListener {
 public:
  string input;

  explicit HogQLErrorListener(string input) : input(std::move(input)) {}

  void syntaxError(
      antlr4::Recognizer* /* recognizer */,
      antlr4::Token* /* offendingSymbol */,
      size_t line,
      size_t charPositionInLine,
      const string& msg,
      exception_ptr /* e */
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
  Json json = Json::object();
  json["error"] = true;
  json["type"] = error_type;
  json["message"] = message;

  Json start_json = Json::object();
  start_json["line"] = 0;
  start_json["column"] = 0;
  start_json["offset"] = start;
  json["start"] = start_json;

  Json end_json = Json::object();
  end_json["line"] = 0;
  end_json["column"] = 0;
  end_json["offset"] = end;
  json["end"] = end_json;

  return json.dump();
}

struct ParserContext {
  // Note: Declaration order matters for destruction - parser must be destroyed before stream, stream before lexer etc.
  unique_ptr<antlr4::ANTLRInputStream> input_stream;
  unique_ptr<HogQLLexer> lexer;
  unique_ptr<antlr4::CommonTokenStream> stream;
  unique_ptr<HogQLErrorListener> error_listener;
  unique_ptr<HogQLParser> parser;

  explicit ParserContext(const string& input) {
    input_stream = std::make_unique<antlr4::ANTLRInputStream>(input.c_str(), input.length());
    lexer = std::make_unique<HogQLLexer>(input_stream.get());
    stream = std::make_unique<antlr4::CommonTokenStream>(lexer.get());
    parser = std::make_unique<HogQLParser>(stream.get());
    parser->removeErrorListeners();
    error_listener = std::make_unique<HogQLErrorListener>(input);
    parser->addErrorListener(error_listener.get());
  }

  // Prevent copying (would cause double-free)
  ParserContext(const ParserContext&) = delete;
  ParserContext& operator=(const ParserContext&) = delete;
};

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
    ParserContext ctx(input);

    HogQLParser::ExprContext* parse_tree;
    try {
      parse_tree = ctx.parser->expr();
    } catch (const antlr4::EmptyStackException& e) {
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeJSONConverter converter(is_internal);
    return converter.visitAsJSONFinal(parse_tree);
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
    ParserContext ctx(input);

    HogQLParser::OrderExprContext* parse_tree;
    try {
      parse_tree = ctx.parser->orderExpr();
    } catch (const antlr4::EmptyStackException& e) {
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeJSONConverter converter(is_internal);
    return converter.visitAsJSONFinal(parse_tree);
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
    ParserContext ctx(input);

    HogQLParser::SelectContext* parse_tree;
    try {
      parse_tree = ctx.parser->select();
    } catch (const antlr4::EmptyStackException& /* e */) {
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeJSONConverter converter(is_internal);
    return converter.visitAsJSONFinal(parse_tree);
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
    ParserContext ctx(input);

    HogQLParser::FullTemplateStringContext* parse_tree;
    try {
      parse_tree = ctx.parser->fullTemplateString();
    } catch (const antlr4::EmptyStackException& /* e */) {
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeJSONConverter converter(is_internal);
    return converter.visitAsJSONFinal(parse_tree);
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
    ParserContext ctx(input);

    HogQLParser::ProgramContext* parse_tree;
    try {
      parse_tree = ctx.parser->program();
    } catch (const antlr4::EmptyStackException& /* e */) {
      return buildWASMError("SyntaxError", "Unmatched curly bracket", 0, input.size());
    }

    HogQLParseTreeJSONConverter converter(is_internal);
    return converter.visitAsJSONFinal(parse_tree);
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
  emscripten::function("parseExpr", &parse_expr);
  emscripten::function("parseOrderExpr", &parse_order_expr);
  emscripten::function("parseSelect", &parse_select);
  emscripten::function("parseFullTemplateString", &parse_full_template_string);
  emscripten::function("parseProgram", &parse_program);
  emscripten::function("parseStringLiteralText", &parse_string_literal_text_wasm);
}