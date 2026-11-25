import {readFileSync} from 'fs'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {ChangeStatus} from '../src/file'
import {Filter} from '../src/filter'

const workflow = yaml.load(
  readFileSync(path.join(__dirname, '../../../../.github/workflows/ci-e2e-playwright.yml'), 'utf8')
) as {jobs: Record<string, {steps?: {id?: string; with?: {filters?: string}}[]}>}
const filter = new Filter(
  Object.values(workflow.jobs)
    .flatMap(job => job.steps ?? [])
    .find(step => step.id === 'changes' && step.with?.filters?.includes('shouldRun:'))!.with!.filters!
)

test.each([
  ['products/messaging/backend/templates/message_preferences/preferences.html', true],
  ['products/messaging/backend/presentation/views/recipient_preferences.py', true],
  ['frontend/public/message-preferences.css', true],
  ['products/messaging/frontend/e2e/message-preferences.spec.ts', true],
  ['products/messaging/backend/tests/fixtures/resend_account.json', false],
  ['products/messaging/backend/services/test_customerio_sync_service.py', false],
  ['products/messaging/backend/test_example.py', false],
  ['products/messaging/backend/conftest.py', false],
  ['products/messaging/backend/api/conftest.py', false]
])('a change to %s starts E2E: %s', (filename, startsE2E) => {
  const result = filter.match([{filename, status: ChangeStatus.Modified}])
  expect(result.shouldRun.length > 0).toBe(startsE2E)
})
