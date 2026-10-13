FUNCTION_NAME = "extractIPv4Substrings"


def EXTRACT_IPV4_SUBSTRINGS_FUNCTION_SQL():
    return rf"""
CREATE OR REPLACE FUNCTION {FUNCTION_NAME} AS
(
  body -> extractAll(body, '(\d\.((25[0-5]|(2[0-4]|1{{0,1}}[0-9]){{0,1}}[0-9])\.){{2,2}}([0-9]))')
)
"""
