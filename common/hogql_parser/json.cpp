#include "json.h"

#include <iomanip>
#include <sstream>
#include <stdexcept>

// Static empty instances for safe returns
static const Json::String emptyString;
static const Json::Array emptyArray;
static const Json::Object emptyObject;

// Initializer list constructor - creates array
Json::Json(std::initializer_list<Json> init) : value(Array(init)) {}

// Object subscript operator
Json& Json::operator[](const std::string& key) {
  if (isNull()) {
    value = Object{};
  }
  if (!isObject()) {
    throw std::runtime_error("Json::operator[](string): not an object");
  }
  return std::get<Object>(value)[key];
}

// Array subscript operator
Json& Json::operator[](size_t index) {
  if (isNull()) {
    value = Array{};
  }
  if (!isArray()) {
    throw std::runtime_error("Json::operator[](size_t): not an array");
  }
  auto& arr = std::get<Array>(value);
  if (index >= arr.size()) {
    arr.resize(index + 1);
  }
  return arr[index];
}

// Value getters
Json::Bool Json::getBool(Bool defaultVal) const {
  if (isBool()) {
    return std::get<Bool>(value);
  }
  return defaultVal;
}

Json::Int Json::getInt(Int defaultVal) const {
  if (isInt()) {
    return std::get<Int>(value);
  }
  if (isFloat()) {
    return static_cast<Int>(std::get<Float>(value));
  }
  return defaultVal;
}

Json::Float Json::getFloat(Float defaultVal) const {
  if (isFloat()) {
    return std::get<Float>(value);
  }
  if (isInt()) {
    return static_cast<Float>(std::get<Int>(value));
  }
  return defaultVal;
}

const Json::String& Json::getString() const {
  if (isString()) {
    return std::get<String>(value);
  }
  return emptyString;
}

const Json::Array& Json::getArray() const {
  if (isArray()) {
    return std::get<Array>(value);
  }
  return emptyArray;
}

const Json::Object& Json::getObject() const {
  if (isObject()) {
    return std::get<Object>(value);
  }
  return emptyObject;
}

Json::Array& Json::getArrayMut() {
  if (isNull()) {
    value = Array{};
  }
  if (!isArray()) {
    throw std::runtime_error("Json::getArrayMut(): not an array");
  }
  return std::get<Array>(value);
}

Json::Object& Json::getObjectMut() {
  if (isNull()) {
    value = Object{};
  }
  if (!isObject()) {
    throw std::runtime_error("Json::getObjectMut(): not an object");
  }
  return std::get<Object>(value);
}

// Array operations
void Json::pushBack(const Json& val) {
  if (isNull()) {
    value = Array{};
  }
  if (!isArray()) {
    throw std::runtime_error("Json::pushBack(): not an array");
  }
  std::get<Array>(value).push_back(val);
}

void Json::pushBack(Json&& val) {
  if (isNull()) {
    value = Array{};
  }
  if (!isArray()) {
    throw std::runtime_error("Json::pushBack(): not an array");
  }
  std::get<Array>(value).push_back(std::move(val));
}

size_t Json::size() const {
  if (isArray()) {
    return std::get<Array>(value).size();
  }
  if (isObject()) {
    return std::get<Object>(value).size();
  }
  if (isString()) {
    return std::get<String>(value).size();
  }
  return 0;
}

bool Json::empty() const {
  if (isArray()) {
    return std::get<Array>(value).empty();
  }
  if (isObject()) {
    return std::get<Object>(value).empty();
  }
  if (isString()) {
    return std::get<String>(value).empty();
  }
  return isNull();
}

// String escaping for JSON output
std::string Json::escapeString(const std::string& s) {
  std::ostringstream escaped;
  escaped << '"';
  for (char c : s) {
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
          escaped << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                  << static_cast<int>(static_cast<unsigned char>(c));
        } else {
          escaped << c;
        }
        break;
    }
  }
  escaped << '"';
  return escaped.str();
}

std::string Json::indentString(int spaces) {
  if (spaces <= 0) {
    return "";
  }
  return std::string(spaces, ' ');
}

std::string Json::dump(int indent) const {
  return dumpImpl(indent, 0);
}

std::string Json::dumpImpl(int indent, int currentIndent) const {
  return std::visit(
      [this, indent, currentIndent](const auto& v) -> std::string {
        using T = std::decay_t<decltype(v)>;

        if constexpr (std::is_same_v<T, Null>) {
          return "null";
        } else if constexpr (std::is_same_v<T, Bool>) {
          return v ? "true" : "false";
        } else if constexpr (std::is_same_v<T, Int>) {
          return std::to_string(v);
        } else if constexpr (std::is_same_v<T, Float>) {
          std::ostringstream oss;
          oss << std::setprecision(17) << v;
          std::string result = oss.str();
          // Ensure it looks like a float (has decimal point or exponent)
          if (result.find('.') == std::string::npos && result.find('e') == std::string::npos &&
              result.find('E') == std::string::npos) {
            result += ".0";
          }
          return result;
        } else if constexpr (std::is_same_v<T, String>) {
          return escapeString(v);
        } else if constexpr (std::is_same_v<T, Raw>) {
          // Raw JSON is already serialized, output as-is
          return v.json;
        } else if constexpr (std::is_same_v<T, Array>) {
          if (v.empty()) {
            return "[]";
          }
          std::ostringstream oss;
          oss << '[';
          bool pretty = indent >= 0;
          int nextIndent = currentIndent + (pretty ? indent : 0);

          for (size_t i = 0; i < v.size(); ++i) {
            if (pretty) {
              oss << '\n' << indentString(nextIndent);
            }
            oss << v[i].dumpImpl(indent, nextIndent);
            if (i < v.size() - 1) {
              oss << ',';
            }
          }
          if (pretty) {
            oss << '\n' << indentString(currentIndent);
          }
          oss << ']';
          return oss.str();
        } else if constexpr (std::is_same_v<T, Object>) {
          if (v.empty()) {
            return "{}";
          }
          std::ostringstream oss;
          oss << '{';
          bool pretty = indent >= 0;
          int nextIndent = currentIndent + (pretty ? indent : 0);

          size_t i = 0;
          for (const auto& [key, val] : v) {
            if (pretty) {
              oss << '\n' << indentString(nextIndent);
            }
            oss << escapeString(key) << ':';
            if (pretty) {
              oss << ' ';
            }
            oss << val.dumpImpl(indent, nextIndent);
            if (i < v.size() - 1) {
              oss << ',';
            }
            ++i;
          }
          if (pretty) {
            oss << '\n' << indentString(currentIndent);
          }
          oss << '}';
          return oss.str();
        }
      },
      value
  );
}
