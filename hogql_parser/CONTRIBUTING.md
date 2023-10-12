# Developing `hogql-parser`

## Mandatory reading

If you're new to Python C/C++ extensions, there are some things you must have in your mind.

### [Objects, Types and Reference Counts in CPython](https://docs.python.org/3/c-api/intro.html#objects-types-and-reference-counts)

   Key takeaways:

   1. `Py_INCREF()` and `Py_DECREF()` need to be used accurately, or there'll be memory leaks (or, less likely, segfaults).
   1. `Py_None`, `Py_True`, and `Py_False` are singletons, but they still need to be incref'd/decref'd - the best way to do create a new reference to them is wrapping them in `Py_NewRef()`.
   1. Pretty much only `PyList_SET_ITEM()` _steals_ references (i.e. assumes ownership of objects passed into it), if you pass an object into any other function and no longer need it after that - remember to `Py_DECREF` it!

### [Building Values in CPython](https://docs.python.org/3/c-api/arg.html#building-values)

   Key takeaways:

   1. Use `Py_BuildValue()` for building tuples, dicts, and lists of static size. Use type-specific functions (e.g. `PyUnicode_FromString()` or `PyList_New()`) otherwise.
   1. `str`-building with `s` involves `strlen`, while `s#` doesn't - it's better to use the latter with C++ strings.
   1. `object`-passing with `O` increments the object's refcount, while doing it with `N` doesn't - we should use `N` pretty much exclusively, because the parse tree converter is about creating new objects (not borrowing).

## Conventions

1. Use `snake_case`. ANTLR is `camelCase`-heavy because of its Java heritage, but both the C++ stdlib and CPython are snaky.
2. Use the `auto` type for ANTLR and ANTLR-derived types, since they can be pretty verbose. Otherwise specify the type explictly.
3. Stay out of Python land as long as possible. E.g. avoid using `PyObject*`s` for bools or strings.
   Do use Python for parsing numbers though - that way we don't need to consider integer overflow.
4. If any child rule results in an AST node, so must the parent rule - once in Python land, always in Python land.
   E.g. it doesn't make sense to create a `vector<PyObject*>`, that should just be a `PyObject*` of Python type `list`.

## How to develop locally on macOS

1. Install libraries:

    ```bash
    brew install boost antlr4-cpp-runtime
    ```

1. Install `hogql_parser` by building from local sources:

    ```bash
    pip install ./hogql_parser
    ```

1. If you now run tests, the locally-built version of `hogql_parser` will be used:

    ```bash
    pytest posthog/hogql/
    ```
