from distutils.core import setup, Extension
import platform

module = Extension(
    "hogql_parser",
    sources=[
        "parser.cpp",
        "string.cpp",
        "HogQLLexer.cpp",
        "HogQLParser.cpp",
        "HogQLParserBaseVisitor.cpp",
        "HogQLParserVisitor.cpp",
    ],
    include_dirs=[
        "/opt/homebrew/include/antlr4-runtime/" if platform.system() == "Darwin" else "/usr/include/antlr4-runtime",
        "/opt/homebrew/include/" if platform.system() == "Darwin" else "/usr/include/",
    ],
    library_dirs=["/opt/homebrew/Cellar/antlr4-cpp-runtime/4.13.1/lib/", "/opt/homebrew/Cellar/boost/1.82.0_1/lib/"],
    libraries=["antlr4-runtime"],
    extra_compile_args=["-std=c++20"],
)

setup(
    name="hogql_parser",
    version="0.1",
    description="HogQL parser",
    ext_modules=[module],
)
