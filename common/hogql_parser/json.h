#ifndef JSON_H
#define JSON_H

#include <cstdint>
#include <initializer_list>
#include <map>
#include <string>
#include <variant>
#include <vector>

// Wrapper for pre-serialized JSON strings that should be embedded directly
struct RawJson {
  std::string json;
  explicit RawJson(std::string s) : json(std::move(s)) {}
};

class Json {
 public:
  using Null = std::nullptr_t;
  using Bool = bool;
  using Int = int64_t;
  using Float = double;
  using String = std::string;
  using Raw = RawJson;
  using Array = std::vector<Json>;
  using Object = std::map<std::string, Json>;

  using Value = std::variant<Null, Bool, Int, Float, String, Raw, Array, Object>;

  // Default constructor - creates null
  Json() : value(nullptr) {}

  // Null
  Json(std::nullptr_t) : value(nullptr) {}

  // Boolean
  Json(bool b) : value(b) {}

  // Integer types
  Json(int i) : value(static_cast<Int>(i)) {}
  Json(int64_t i) : value(i) {}
  Json(size_t i) : value(static_cast<Int>(i)) {}

  // Floating point
  Json(double d) : value(d) {}
  Json(float f) : value(static_cast<Float>(f)) {}

  // String types
  Json(const char* s) : value(String(s)) {}
  Json(const std::string& s) : value(s) {}
  Json(std::string&& s) : value(std::move(s)) {}

  // Array
  Json(const Array& arr) : value(arr) {}
  Json(Array&& arr) : value(std::move(arr)) {}
  Json(std::initializer_list<Json> init);

  // Object
  Json(const Object& obj) : value(obj) {}
  Json(Object&& obj) : value(std::move(obj)) {}

  // Raw JSON (pre-serialized)
  Json(const RawJson& raw) : value(raw) {}
  Json(RawJson&& raw) : value(std::move(raw)) {}

  // Copy and move
  Json(const Json&) = default;
  Json(Json&&) = default;
  Json& operator=(const Json&) = default;
  Json& operator=(Json&&) = default;

  // Assignment operators for convenience
  Json& operator=(std::nullptr_t) {
    value = nullptr;
    return *this;
  }
  Json& operator=(bool b) {
    value = b;
    return *this;
  }
  Json& operator=(int i) {
    value = static_cast<Int>(i);
    return *this;
  }
  Json& operator=(int64_t i) {
    value = i;
    return *this;
  }
  Json& operator=(double d) {
    value = d;
    return *this;
  }
  Json& operator=(const char* s) {
    value = String(s);
    return *this;
  }
  Json& operator=(const std::string& s) {
    value = s;
    return *this;
  }
  Json& operator=(std::string&& s) {
    value = std::move(s);
    return *this;
  }

  // Object access - creates object if needed
  Json& operator[](const std::string& key);
  Json& operator[](const char* key) { return (*this)[std::string(key)]; }

  // Array access - creates array if needed
  Json& operator[](size_t index);

  // Type checks
  bool isNull() const { return std::holds_alternative<Null>(value); }
  bool isBool() const { return std::holds_alternative<Bool>(value); }
  bool isInt() const { return std::holds_alternative<Int>(value); }
  bool isFloat() const { return std::holds_alternative<Float>(value); }
  bool isNumber() const { return isInt() || isFloat(); }
  bool isString() const { return std::holds_alternative<String>(value); }
  bool isArray() const { return std::holds_alternative<Array>(value); }
  bool isObject() const { return std::holds_alternative<Object>(value); }
  bool isRaw() const { return std::holds_alternative<Raw>(value); }

  // Value getters
  Bool getBool(Bool defaultVal = false) const;
  Int getInt(Int defaultVal = 0) const;
  Float getFloat(Float defaultVal = 0.0) const;
  const String& getString() const;
  const Array& getArray() const;
  const Object& getObject() const;

  // Mutable access
  Array& getArrayMut();
  Object& getObjectMut();

  // Array operations
  void pushBack(const Json& val);
  void pushBack(Json&& val);
  size_t size() const;
  bool empty() const;

  // Serialization
  std::string dump(int indent = -1) const;

  // Static factory for explicit object/array creation
  static Json object() { return Json(Object{}); }
  static Json array() { return Json(Array{}); }
  static Json raw(const std::string& jsonStr) { return Json(RawJson(jsonStr)); }
  static Json raw(std::string&& jsonStr) { return Json(RawJson(std::move(jsonStr))); }

  // String escaping utility (for manual JSON construction)
  static std::string escapeString(const std::string& s);

 private:
  Value value;

  std::string dumpImpl(int indent, int currentIndent) const;
  static std::string indentString(int spaces);
};

#endif  // JSON_H
