import platform

from setuptools import Extension, setup

system = platform.system()
if system not in ("Darwin", "Linux"):
    raise Exception("Only Linux and macOS are supported by hogql_parser")

is_macos = system == "Darwin"
homebrew_location = "/opt/homebrew" if platform.machine() == "arm64" else "/usr/local"

module = Extension(
    "hogql_parser",
    sources=[
        "HogQLLexer.cpp",
        "HogQLParser.cpp",
        "HogQLParserBaseVisitor.cpp",
        "HogQLParserVisitor.cpp",
        "error.cpp",
        "string.cpp",
        "json.cpp",
        "parser_python.cpp",
    ],
    include_dirs=(
        [
            f"{homebrew_location}/include/",
            f"{homebrew_location}/include/antlr4-runtime/",
        ]
        if is_macos
        else ["/usr/include/", "/usr/include/antlr4-runtime/"]
    ),
    library_dirs=[f"{homebrew_location}/lib/"] if is_macos else ["/usr/lib/", "/usr/lib64/"],
    libraries=["antlr4-runtime"],
    extra_compile_args=["-std=c++20"],
)

# Project metadata lives in pyproject.toml [project]; this file only wires up
# the C++ extension build, which setuptools cannot express declaratively.
setup(
    packages=["hogql_parser-stubs"],
    include_package_data=True,
    ext_modules=[module],
)
