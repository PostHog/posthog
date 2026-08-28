import {backslashEscape, shellEscape} from '../src/list-format/shell-escape'

describe('escape() backslash escapes every character except subset of definitely safe characters', () => {
  test('simple filename should not be modified', () => {
    expect(backslashEscape('file.txt')).toBe('file.txt')
  })

  test('directory separator should be preserved and not escaped', () => {
    expect(backslashEscape('path/to/file.txt')).toBe('path/to/file.txt')
  })

  test('spaces should be escaped with backslash', () => {
    expect(backslashEscape('file with space')).toBe('file\\ with\\ space')
  })

  test('quotes should be escaped with backslash', () => {
    expect(backslashEscape('file\'with quote"')).toBe('file\\\'with\\ quote\\"')
  })

  test('$variables should be escaped', () => {
    expect(backslashEscape('$var')).toBe('\\$var')
  })
})

describe('shellEscape() returns human readable filenames with as few escaping applied as possible', () => {
  test('simple filename should not be modified', () => {
    expect(shellEscape('file.txt')).toBe('file.txt')
  })

  test('directory separator should be preserved and not escaped', () => {
    expect(shellEscape('path/to/file.txt')).toBe('path/to/file.txt')
  })

  test('filename with spaces should be quoted', () => {
    expect(shellEscape('file with space')).toBe("'file with space'")
  })

  test('filename with spaces should be quoted', () => {
    expect(shellEscape('file with space')).toBe("'file with space'")
  })

  test('filename with $ should be quoted', () => {
    expect(shellEscape('$var')).toBe("'$var'")
  })

  test('filename with " should be quoted', () => {
    expect(shellEscape('file"name')).toBe("'file\"name'")
  })

  test('filename with single quote should be wrapped in double quotes', () => {
    expect(shellEscape("file'with quote")).toBe('"file\'with quote"')
  })

  test('filename with single quote and special characters is split and quoted/escaped as needed', () => {
    expect(shellEscape("file'with $quote")).toBe("file\\''with $quote'")
  })
})
