#include <boost/algorithm/string.hpp>

#include "error.h"
#include "string.h"

using namespace std;

string replace_common_escape_characters(string text) {
  // Copied from clickhouse_driver/util/escape.py
  boost::replace_all(text, "\\a", "\a");
  boost::replace_all(text, "\\b", "\b");
  boost::replace_all(text, "\\f", "\f");
  boost::replace_all(text, "\\n", "\n");
  boost::replace_all(text, "\\r", "\r");
  boost::replace_all(text, "\\t", "\t");
  boost::replace_all(text, "\\v", "\v");
  boost::replace_all(text, "\\0", "");  // NUL characters are ignored
  boost::replace_all(text, "\\\\", "\\");

  return text;
}

string parse_string_literal_text(string text) {
  size_t original_text_size = text.size();
  if (original_text_size == 0) {
    throw ParsingError("Encountered an unexpected empty string input");
  }
  const char first_char = text.front();
  const char last_char = text.back();
  if (first_char == '\'' && last_char == '\'') {
    text = text.substr(1, original_text_size - 2);
    boost::replace_all(text, "''", "'");
    boost::replace_all(text, "\\'", "'");
  } else if (first_char == '"' && last_char == '"') {
    text = text.substr(1, original_text_size - 2);
    boost::replace_all(text, "\"\"", "\"");
    boost::replace_all(text, "\\\"", "\"");
  } else if (first_char == '`' && last_char == '`') {
    text = text.substr(1, original_text_size - 2);
    boost::replace_all(text, "``", "`");
    boost::replace_all(text, "\\`", "`");
  } else if (first_char == '{' && last_char == '}') {
    text = text.substr(1, original_text_size - 2);
    boost::replace_all(text, "{{", "{");
    boost::replace_all(text, "\\{", "{");
  } else {
    throw SyntaxError("Invalid string literal, must start and end with the same quote type: " + text);
  }
  return replace_common_escape_characters(text);
}


string parse_string_literal_ctx(antlr4::tree::TerminalNode* node) {
  string text = node->getText();
  try {
    return parse_string_literal_text(text);
  } catch (SyntaxError& e) {
    throw SyntaxError(e.what(), node->getSymbol()->getStartIndex(), node->getSymbol()->getStopIndex() + 1);
  } catch (ParsingError& e) {
    throw ParsingError(e.what(), node->getSymbol()->getStartIndex(), node->getSymbol()->getStopIndex() + 1);
  }
}

string parse_string_text_ctx(antlr4::tree::TerminalNode* node, bool escape_quotes) {
  string text = node->getText();
  try {
    if (escape_quotes) {
      boost::replace_all(text, "''", "'");
      boost::replace_all(text, "\\'", "'");
    }
    boost::replace_all(text, "\\{", "{");
    return replace_common_escape_characters(text);
  } catch (SyntaxError& e) {
    throw SyntaxError(e.what(), node->getSymbol()->getStartIndex(), node->getSymbol()->getStopIndex() + 1);
  } catch (ParsingError& e) {
    throw ParsingError(e.what(), node->getSymbol()->getStartIndex(), node->getSymbol()->getStopIndex() + 1);
  }
}
