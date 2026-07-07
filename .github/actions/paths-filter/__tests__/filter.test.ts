import {Filter} from '../src/filter'
import {File, ChangeStatus} from '../src/file'

describe('yaml filter parsing tests', () => {
  test('throws if yaml is not a dictionary', () => {
    const yaml = 'not a dictionary'
    const t = () => new Filter(yaml)
    expect(t).toThrow(/^Invalid filter.*/)
  })
  test('throws if pattern is not a string', () => {
    const yaml = `
    src:
      - src/**/*.js
      - dict:
          some: value
    `
    const t = () => new Filter(yaml)
    expect(t).toThrow(/^Invalid filter.*/)
  })
  test('throws on a "!" pattern nested inside a change-status array instead of silently over-matching', () => {
    const yaml = `
    changed:
      - added|modified: ['src/**', '!src/vendor/**']
    `
    const t = () => new Filter(yaml)
    expect(t).toThrow(/^Invalid filter.*/)
  })
})

describe('matching tests', () => {
  test('matches single inline rule', () => {
    const yaml = `
    src: "src/**/*.js"
    `
    let filter = new Filter(yaml)
    const files = modified(['src/app/module/file.js'])
    const match = filter.match(files)
    expect(match.src).toEqual(files)
  })
  test('matches single rule in single group', () => {
    const yaml = `
    src:
      - src/**/*.js
    `
    const filter = new Filter(yaml)
    const files = modified(['src/app/module/file.js'])
    const match = filter.match(files)
    expect(match.src).toEqual(files)
  })

  test('no match when file is in different folder', () => {
    const yaml = `
    src:
      - src/**/*.js
    `
    const filter = new Filter(yaml)
    const match = filter.match(modified(['not_src/other_file.js']))
    expect(match.src).toEqual([])
  })

  test('match only within second groups ', () => {
    const yaml = `
    src:
      - src/**/*.js
    test:
      - test/**/*.js
    `
    const filter = new Filter(yaml)
    const files = modified(['test/test.js'])
    const match = filter.match(files)
    expect(match.src).toEqual([])
    expect(match.test).toEqual(files)
  })

  test('match only withing second rule of single group', () => {
    const yaml = `
    src:
      - src/**/*.js
      - test/**/*.js
    `
    const filter = new Filter(yaml)
    const files = modified(['test/test.js'])
    const match = filter.match(files)
    expect(match.src).toEqual(files)
  })

  test('matches anything', () => {
    const yaml = `
    any:
      - "**"
    `
    const filter = new Filter(yaml)
    const files = modified(['test/test.js'])
    const match = filter.match(files)
    expect(match.any).toEqual(files)
  })

  test('globbing matches path where file or folder name starts with dot', () => {
    const yaml = `
    dot:
      - "**/*.js"
    `
    const filter = new Filter(yaml)
    const files = modified(['.test/.test.js'])
    const match = filter.match(files)
    expect(match.dot).toEqual(files)
  })

  test('matches all except tsx and less files (negate a group with or-ed parts)', () => {
    const yaml = `
    backend:
      - '!(**/*.tsx|**/*.less)'
    `
    const filter = new Filter(yaml)
    const tsxFiles = modified(['src/ui.tsx'])
    const lessFiles = modified(['src/ui.less'])
    const pyFiles = modified(['src/server.py'])

    const tsxMatch = filter.match(tsxFiles)
    const lessMatch = filter.match(lessFiles)
    const pyMatch = filter.match(pyFiles)

    expect(tsxMatch.backend).toEqual([])
    expect(lessMatch.backend).toEqual([])
    expect(pyMatch.backend).toEqual(pyFiles)
  })

  test('excludes multiple patterns and filters file lists', () => {
    const yaml = `
    backend:
      - 'pkg/a/b/c/**'
      - '!**/*.jpeg'
      - '!**/*.md'
    `
    const filter = new Filter(yaml)

    const typescriptFiles = modified(['pkg/a/b/c/some-class.ts', 'pkg/a/b/c/src/main/some-class.ts'])
    const otherPkgTypescriptFiles = modified(['pkg/x/y/z/some-class.ts', 'pkg/x/y/z/src/main/some-class.ts'])
    const otherPkgJpegFiles = modified(['pkg/x/y/z/some-pic.jpeg', 'pkg/x/y/z/src/main/jpeg/some-pic.jpeg'])
    const docsFiles = modified([
      'pkg/a/b/c/some-pics.jpeg',
      'pkg/a/b/c/src/main/jpeg/some-pic.jpeg',
      'pkg/a/b/c/src/main/some-docs.md',
      'pkg/a/b/c/some-docs.md'
    ])

    const typescriptMatch = filter.match(typescriptFiles)
    const otherPkgTypescriptMatch = filter.match(otherPkgTypescriptFiles)
    const docsMatch = filter.match(docsFiles)
    const otherPkgJpegMatch = filter.match(otherPkgJpegFiles)

    expect(typescriptMatch.backend).toEqual(typescriptFiles)
    expect(otherPkgTypescriptMatch.backend).toEqual([])
    expect(docsMatch.backend).toEqual([])
    expect(otherPkgJpegMatch.backend).toEqual([])
  })

  test('matches path based on rules included using YAML anchor', () => {
    const yaml = `
    shared: &shared
      - common/**/*
      - config/**/*
    src:
      - *shared
      - src/**/*
    `
    const filter = new Filter(yaml)
    const files = modified(['config/settings.yml'])
    const match = filter.match(files)
    expect(match.src).toEqual(files)
  })

  describe('include/exclude matching', () => {
    const backendExceptDocs = `
    backend:
      - 'posthog/**'
      - 'products/**/backend/**'
      - '!**/*.md'
    `
    const everythingExceptDocs = `
    any:
      - '!**/*.md'
    `

    const cases: [string, string, string, string, boolean][] = [
      ['include matches', backendExceptDocs, 'backend', 'posthog/models.py', true],
      ['second include matches', backendExceptDocs, 'backend', 'products/foo/backend/task.py', true],
      ['exclude vetoes a matched include', backendExceptDocs, 'backend', 'posthog/README.md', false],
      ['exclude vetoes a matched second include', backendExceptDocs, 'backend', 'products/foo/backend/notes.md', false],
      ['no include matches', backendExceptDocs, 'backend', 'frontend/src/app.tsx', false],
      ['exclude-only matches everything else', everythingExceptDocs, 'any', 'src/app.ts', true],
      ['exclude-only still vetoes', everythingExceptDocs, 'any', 'docs/guide.md', false]
    ]
    test.each(cases)('%s', (_label, yaml, key, filename, shouldMatch) => {
      const filter = new Filter(yaml)
      const files = modified([filename])
      const match = filter.match(files)
      expect(match[key]).toEqual(shouldMatch ? files : [])
    })
  })
})

describe('matching specific change status', () => {
  test('does not match modified file as added', () => {
    const yaml = `
    add:
      - added: "**/*"
    `
    let filter = new Filter(yaml)
    const match = filter.match(modified(['file.js']))
    expect(match.add).toEqual([])
  })

  test('match added file as added', () => {
    const yaml = `
    add:
      - added: "**/*"
    `
    let filter = new Filter(yaml)
    const files = [{status: ChangeStatus.Added, filename: 'file.js'}]
    const match = filter.match(files)
    expect(match.add).toEqual(files)
  })

  test('matches when multiple statuses are configured', () => {
    const yaml = `
    addOrModify:
      - added|modified: "**/*"
    `
    let filter = new Filter(yaml)
    const files = [{status: ChangeStatus.Modified, filename: 'file.js'}]
    const match = filter.match(files)
    expect(match.addOrModify).toEqual(files)
  })

  test('matches when using an anchor', () => {
    const yaml = `
    shared: &shared
      - common/**/*
      - config/**/*
    src:
      - modified: *shared
    `
    let filter = new Filter(yaml)
    const files = modified(['config/file.js', 'common/anotherFile.js'])
    const match = filter.match(files)
    expect(match.src).toEqual(files)
  })
})

function modified(paths: string[]): File[] {
  return paths.map(filename => {
    return {filename, status: ChangeStatus.Modified}
  })
}
