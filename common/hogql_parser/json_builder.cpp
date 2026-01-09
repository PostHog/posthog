#include "json_builder.h"

#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>

JSONBuilder::JSONBuilder() {
  // Start with clean state
}

void JSONBuilder::addCommaIfNeeded() {
  if (!context_stack.empty() && !needs_comma.empty() && needs_comma.back()) {
    buffer << ",";
  }
}

void JSONBuilder::markItemAdded() {
  if (!needs_comma.empty()) {
    needs_comma.back() = true;
  }
}

void JSONBuilder::startObject() {
  addCommaIfNeeded();
  buffer << "{";
  context_stack.push_back(true);  // true = object
  needs_comma.push_back(false);
}

void JSONBuilder::endObject() {
  if (context_stack.empty() || !context_stack.back()) {
    // Error: not in object context
    return;
  }
  buffer << "}";
  context_stack.pop_back();
  needs_comma.pop_back();
  markItemAdded();
}

void JSONBuilder::startArray() {
  addCommaIfNeeded();
  buffer << "[";
  context_stack.push_back(false);  // false = array
  needs_comma.push_back(false);
}

void JSONBuilder::endArray() {
  if (context_stack.empty() || context_stack.back()) {
    // Error: not in array context
    return;
  }
  buffer << "]";
  context_stack.pop_back();
  needs_comma.pop_back();
  markItemAdded();
}

void JSONBuilder::addKey(const string& key) {
  addCommaIfNeeded();
  buffer << "\"" << escapeString(key) << "\":";
  if (!needs_comma.empty()) {
    needs_comma.back() = false;  // Don't add comma before value
  }
}

void JSONBuilder::addString(const string& value) {
  addCommaIfNeeded();
  buffer << "\"" << escapeString(value) << "\"";
  markItemAdded();
}

void JSONBuilder::addInt(int64_t value) {
  addCommaIfNeeded();
  buffer << value;
  markItemAdded();
}

void JSONBuilder::addFloat(double value) {
  addCommaIfNeeded();
  // Handle special float values
  if (value != value) {  // NaN
    buffer << "\"NaN\"";
  } else if (value == numeric_limits<double>::infinity()) {
    buffer << "\"Infinity\"";
  } else if (value == -numeric_limits<double>::infinity()) {
    buffer << "\"-Infinity\"";
  } else {
    buffer << std::setprecision(17) << value;

    // Ensure decimal point for whole numbers
    if (floor(value) == value) {
      buffer << ".0";
    }
  }
  markItemAdded();
}

void JSONBuilder::addBool(bool value) {
  addCommaIfNeeded();
  buffer << (value ? "true" : "false");
  markItemAdded();
}

void JSONBuilder::addNull() {
  addCommaIfNeeded();
  buffer << "null";
  markItemAdded();
}

void JSONBuilder::addRawJSON(const string& json) {
  addCommaIfNeeded();
  buffer << json;
  markItemAdded();
}

string JSONBuilder::escapeString(const string& str) {
  stringstream escaped;
  for (char c : str) {
    switch (c) {
      case '"':
        escaped << "\\\"";
        break;
      case '\\':
        escaped << "\\\\";
        break;
      case '\b':
        escaped << "\\b";
        break;
      case '\f':
        escaped << "\\f";
        break;
      case '\n':
        escaped << "\\n";
        break;
      case '\r':
        escaped << "\\r";
        break;
      case '\t':
        escaped << "\\t";
        break;
      default:
        if (static_cast<unsigned char>(c) < 0x20) {
          // Control characters: use \uXXXX encoding
          escaped << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                  << static_cast<int>(static_cast<unsigned char>(c));
        } else {
          // Pass through all other bytes unchanged (including UTF-8 multibyte sequences)
          escaped << c;
        }
        break;
    }
  }
  return escaped.str();
}

string JSONBuilder::toString() const {
  return buffer.str();
}

void JSONBuilder::addPosition(const string& key, const Position& pos) {
  addKey(key);
  startObject();
  addKey("line");
  addInt(pos.line);
  addKey("column");
  addInt(pos.column);
  addKey("offset");
  addInt(pos.offset);
  endObject();
}

void JSONBuilder::addNodeType(const string& node_type) {
  addKey("node");
  addString(node_type);
}