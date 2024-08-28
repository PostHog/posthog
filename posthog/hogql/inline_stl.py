# TODO: this needs a better buildchain
# Functions defined here will be inlined into the HogQL bytecode

INLINE_STL = {
    "arrayExists": """
        fn arrayExists(func, arr) {
          for (let i in arr) {
            if (func(i)) {
              return true
            }
          }
          return false
        }
    """,
    "arrayMap": """
        fn arrayMap(func, arr) {
          let result := []
          for (let i in arr) {
            result := arrayPushBack(result, func(i))
          }
          return result
        }
    """,
    "arrayFilter": """
        fn arrayFilter(func, arr) {
          let result := []
          for (let i in arr) {
            if (func(i)) {
              result := arrayPushBack(result, i)
            }
          }
          return result
        }
    """,
}
