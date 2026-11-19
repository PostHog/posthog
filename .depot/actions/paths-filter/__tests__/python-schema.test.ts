import {readFileSync} from 'fs'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {ChangeStatus} from '../src/file'
import {Filter} from '../src/filter'

const workflow = yaml.load(
  readFileSync(path.join(__dirname, '../../../../.github/workflows/ci-python.yml'), 'utf8')
) as {jobs: {changes: {steps: {id?: string; with?: {filters?: string}}[]}}}
const filter = new Filter(workflow.jobs.changes.steps.find(step => step.id === 'filter')!.with!.filters!)

const inputs = [
  'frontend/src/queries/schema.json',
  'posthog/schema.py',
  'posthog/schema_enums.py',
  'bin/build-schema-python.sh',
  'bin/patch-schema-array-discriminators.py',
  'bin/patch-schema-property-filter-discriminator.py',
  'bin/split-schema-enums.py',
  'pyproject.toml',
  'tools/hogli/pyproject.toml',
  'ruff.toml',
  '.ruff.toml',
  'posthog/ruff.toml',
  'posthog/.ruff.toml',
  'uv.lock',
  '.github/actions/paths-filter/src/filter.ts',
  '.github/workflows/ci-python.yml'
]

test.each([ChangeStatus.Added, ChangeStatus.Modified, ChangeStatus.Deleted])(
  'Python schema %s inputs reach both the job and generation check',
  status => {
    const files = inputs.map(filename => ({filename, status}))
    const result = filter.match(files)
    expect(result.schema_python).toEqual(files)
    expect(result.python).toEqual(files)
  }
)

test('unrelated Python changes run Python checks without schema generation', () => {
  const files = ['posthog/api/test/test_insight.py', 'pnpm-lock.yaml', 'package.json'].map(filename => ({
    filename,
    status: ChangeStatus.Modified
  }))
  const result = filter.match(files)
  expect(result.python).toEqual([files[0]])
  expect(result.schema_python).toEqual([])
})
