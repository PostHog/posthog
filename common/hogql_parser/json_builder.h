#ifndef JSON_BUILDER_H
#define JSON_BUILDER_H

#include <string>
#include <vector>
#include <sstream>
#include <iomanip>

using namespace std;

/**
 * Lightweight JSON builder for constructing JSON strings.
 *
 * This class provides a simple API for building JSON objects and arrays
 * without requiring external JSON libraries. It's designed specifically
 * for converting ANTLR parse trees to JSON AST representations.
 *
 * Example usage:
 *   JSONBuilder json;
 *   json.startObject();
 *   json.addKey("node"); json.addString("Constant");
 *   json.addKey("value"); json.addInt(42);
 *   json.endObject();
 *   string result = json.toString(); // {"node":"Constant","value":42}
 */
class JSONBuilder {
private:
    stringstream buffer;
    vector<bool> context_stack; // true = object, false = array
    vector<bool> needs_comma;   // Track if next item needs comma

    void addCommaIfNeeded();
    void markItemAdded();

public:
    JSONBuilder();

    // Object/Array structure
    void startObject();
    void endObject();
    void startArray();
    void endArray();

    // Key for object properties
    void addKey(const string& key);

    // Values
    void addString(const string& value);
    void addInt(int64_t value);
    void addFloat(double value);
    void addBool(bool value);
    void addNull();

    // Add raw JSON (for embedding already-serialized JSON)
    void addRawJSON(const string& json);

    // Utility: escape string for JSON
    static string escapeString(const string& str);

    // Get the final JSON string
    string toString() const;

    // AST-specific helpers
    struct Position {
        size_t line;
        size_t column;
        size_t offset;
    };

    void addPosition(const string& key, const Position& pos);
    void addNodeType(const string& node_type);
};

#endif // JSON_BUILDER_H