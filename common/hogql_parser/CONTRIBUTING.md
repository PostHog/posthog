# Developing `hogql-parser`

## Mandatory reading

If you're new to Python C/C++ extensions, there are some things you must have in mind. The [Python/C API Reference Manual](https://docs.python.org/3/c-api/index.html) is worth a read as a whole.

The three pages below are must-reads though. They're key to writing production-ready code:

### [Objects, Types and Reference Counts](https://docs.python.org/3/c-api/intro.html#objects-types-and-reference-counts)

Key takeaways:

1. `Py_INCREF()` and `Py_DECREF()` need to be used accurately, or there'll be memory leaks (or, less likely, segfaults). This also applies to early exits, such as these caused by an error.
1. `Py_None`, `Py_True`, and `Py_False` are singletons, but they still need to be incref'd/decref'd - the best way to do create a new reference to them is wrapping them in `Py_NewRef()`.
1. Pretty much only `PyList_SET_ITEM()` _steals_ references (i.e. assumes ownership of objects passed into it) - if you pass an object into any other function and no longer need it after that, remember to `Py_DECREF` it!

### [Exception Handling](https://docs.python.org/3/c-api/exceptions.html)

Key takeaways:

1. If a Python exception has been raised, the module method that was called from Python must stop execution and return `NULL` immediately.
   > In `HogQLParseTreeConverter`, we are able to use C++ exceptions: throwing `SyntaxException`,
   > `NotImplementedException`, or `ParsingException` results in the same exception being raised in Python as
   > expected. Note that if a `visitAsFoo` call throws an exception and there are `PyObject*`s in scope, we have to
   > remember about cleaning up their refcounts. At such call sites, a `try {} catch (...) {}` block is appropriate.
1. For all Python/C API calls returning `PyObject*`, make sure `NULL` wasn't returned - if it was, then something failed and the Python runtime has already set an exception (e.g. a `MemoryError`). The same applies to calls returning `int` - there the error value is `-1`. Exception: in `PyArg_Foo` functions failure is signaled by `0` and success by `1`.
   > In `HogQLParseTreeConverter`, these internal Python failures are handled simply by throwing
   > `PyInternalException`.

### [Building Values](https://docs.python.org/3/c-api/arg.html#building-values)

Key takeaways:

1. Use `Py_BuildValue()` for building tuples, dicts, and lists of static size. Use type-specific functions (e.g. `PyUnicode_FromString()` or `PyList_New()`) otherwise.
1. `str`-building with `s` involves `strlen`, while `s#` doesn't - it's better to use the latter with C++ strings.
1. `object`-passing with `O` increments the object's refcount, while doing it with `N` doesn't - we should use `N` pretty much exclusively, because the parse tree converter is about creating new objects (not borrowing).

## Conventions

1. Use `snake_case`. ANTLR is `camelCase`-heavy because of its Java heritage, but both the C++ stdlib and CPython are snaky.
2. Use the `auto` type for ANTLR and ANTLR-derived types, since they can be pretty verbose. Otherwise, specify the type explicitly.
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
   pip install ./common/hogql_parser
   ```

   > If you're getting compilation errors like this on macOS Sonoma:  
   > `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/c++/v1/cstring:66:5: error: <cstring> tried including <string.h> but didn't find libc++'s <string.h> header.`  
   > Then you may need to remove Xcode Command Line Tools:  
   > `sudo rm -rf /Library/Developer/CommandLineTools`

1. If you now run tests, the locally-built version of `hogql_parser` will be used:

   ```bash
   pytest posthog/hogql/
   ```

## How to install dependencies on Ubuntu

Antlr runtime provided in Ubuntu packages might be of an older version, which results in compilation errors.

In that case run commands from [this step](https://github.com/PostHog/posthog/blob/4fba6a63e351131fdb27b85e7ba436446fdb3093/.github/actions/run-backend-tests/action.yml#L100).
