#include <boost/algorithm/string.hpp>
#include "antlr4-runtime.h"

using namespace std;

// TODO: Cover with tests

string parse_string(const std::string& text) {
    if (text.front() == text.back() && (text.front() == '\'' || text.front() == '"' || text.front() == '`' || text.front() == '{')) {
        std::string result = text.substr(1, text.size() - 2);
        boost::replace_all(result, "''", "'");
        boost::replace_all(result, "\\\"", "\"");
        boost::replace_all(result, "\\'", "'");
        boost::replace_all(result, "\"\"", "\"");
        boost::replace_all(result, "\\`", "`");
        boost::replace_all(result, "``", "`");
        boost::replace_all(result, "\\{", "{");
        boost::replace_all(result, "{{", "{");
        boost::replace_all(result, "\\\\", "\\");
        boost::replace_all(result, "\\b", "\b");
        boost::replace_all(result, "\\f", "\f");
        boost::replace_all(result, "\\r", "\r");
        boost::replace_all(result, "\\n", "\n");
        boost::replace_all(result, "\\t", "\t");
        boost::replace_all(result, "\\0", "\0");
        boost::replace_all(result, "\\a", "\a");
        boost::replace_all(result, "\\v", "\v");
        return result;
    } else {
        throw std::runtime_error("Invalid string literal, must start and end with the same quote type: " + text);
    }
}

string parse_string_literal(antlr4::tree::TerminalNode* node) {
    return parse_string(node->getText());
}
