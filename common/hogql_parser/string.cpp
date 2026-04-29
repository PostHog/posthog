#include <cctype>

#include "error.h"
#include "string.h"

using namespace std;

string replace_common_escape_characters(string text) {
  // Escape map derived from clickhouse_driver's escape_chars_map:
  // https://github.com/mymarilyn/clickhouse-driver/blob/master/clickhouse_driver/util/escape.py#L9
  //
  // Single-pass left-to-right scan so that an escaped backslash (\\)
  // is consumed before the next character is inspected.
  string result;
  result.reserve(text.size());
  size_t i = 0;
  size_t length = text.size();
  while (i < length) {
    if (text[i] == '\\' && i + 1 < length) {
      char next = text[i + 1];
      switch (next) {
        case 'b': result += '\b'; i += 2; continue;
        case 'f': result += '\f'; i += 2; continue;
        case 'r': result += '\r'; i += 2; continue;
        case 'n': result += '\n'; i += 2; continue;
        case 't': result += '\t'; i += 2; continue;
        case '0': /* NUL characters are ignored */ i += 2; continue;
        case 'a': result += '\a'; i += 2; continue;
        case 'v': result += '\v'; i += 2; continue;
        case '\\': result += '\\'; i += 2; continue;
        default: break;
      }
    }
    result += text[i];
    i += 1;
  }
  return result;
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
    replace_all(text, "''", "'");
    replace_all(text, "\\'", "'");
  } else if (first_char == '"' && last_char == '"') {
    text = text.substr(1, original_text_size - 2);
    replace_all(text, "\"\"", "\"");
    replace_all(text, "\\\"", "\"");
  } else if (first_char == '`' && last_char == '`') {
    text = text.substr(1, original_text_size - 2);
    replace_all(text, "``", "`");
    replace_all(text, "\\`", "`");
  } else if (first_char == '{' && last_char == '}') {
    text = text.substr(1, original_text_size - 2);
    replace_all(text, "{{", "{");
    replace_all(text, "\\{", "{");
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
      replace_all(text, "''", "'");
      replace_all(text, "\\'", "'");
    }
    replace_all(text, "\\{", "{");
    return replace_common_escape_characters(text);
  } catch (SyntaxError& e) {
    throw SyntaxError(e.what(), node->getSymbol()->getStartIndex(), node->getSymbol()->getStopIndex() + 1);
  } catch (ParsingError& e) {
    throw ParsingError(e.what(), node->getSymbol()->getStartIndex(), node->getSymbol()->getStopIndex() + 1);
  }
}

string join(const vector<string>& tokens, const string& sep) {
  if (tokens.empty()) return "";
  string result;
  for (size_t i = 0; i < tokens.size(); ++i) {
    if (i > 0) result += sep;
    result += tokens[i];
  }
  return result;
}

void to_lower(string& s) {
  for (char& c : s) {
    c = std::tolower(static_cast<unsigned char>(c));
  }
}

string to_lower_copy(const string& s) {
  string result = s;
  to_lower(result);
  return result;
}

void replace_all(string& str, const string& from, const string& to) {
  if (from.empty()) return;
  size_t pos = 0;
  while ((pos = str.find(from, pos)) != string::npos) {
    str.replace(pos, from.length(), to);
    pos += to.length();
  }
}
