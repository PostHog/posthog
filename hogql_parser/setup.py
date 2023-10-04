from distutils.core import setup, Extension
import platform

arch = "aarch64" if platform.machine() == "arm64" else "x86_64"
module = Extension(
    "hogql_parser",
    sources=[
        "HogQLLexer.cpp",
        "HogQLParser.cpp",
        "HogQLParserBaseVisitor.cpp",
        "HogQLParserVisitor.cpp",
        "error.cpp",
        "string.cpp",
        "parser.cpp",
    ],
    include_dirs=[
        "/opt/homebrew/include/antlr4-runtime/"
        if platform.system() == "Darwin"
        else "/usr/local/include/antlr4-runtime/",
        "/opt/homebrew/include/" if platform.system() == "Darwin" else "/usr/include/",
    ],
    library_dirs=[
        "/opt/homebrew/Cellar/antlr4-cpp-runtime/4.13.1/lib/" if platform.system() == "Darwin" else "/usr/local/lib/",
        "/opt/homebrew/Cellar/boost/1.82.0_1/lib/" if platform.system() == "Darwin" else f"/usr/lib/{arch}-linux-gnu/",
    ],
    libraries=["antlr4-runtime"],
    extra_compile_args=["-std=c++20"],
)

setup(
    name="hogql_parser",
    version="0.1",
    description="HogQL parser",
    ext_modules=[module],
)
