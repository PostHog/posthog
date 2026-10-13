import {csvEscape} from '../src/list-format/csv-escape'

describe('csvEscape() backslash escapes every character except subset of definitely safe characters', () => {
  test('simple filename should not be modified', () => {
    expect(csvEscape('file.txt')).toBe('file.txt')
  })

  test('directory separator should be preserved and not escaped', () => {
    expect(csvEscape('path/to/file.txt')).toBe('path/to/file.txt')
  })

  test('filename with spaces should be quoted', () => {
    expect(csvEscape('file with space')).toBe('"file with space"')
  })

  test('filename with "," should be quoted', () => {
    expect(csvEscape('file, with coma')).toBe('"file, with coma"')
  })

  test('Double quote should be escaped by another double quote', () => {
    expect(csvEscape('file " with double quote')).toBe('"file "" with double quote"')
  })
})
