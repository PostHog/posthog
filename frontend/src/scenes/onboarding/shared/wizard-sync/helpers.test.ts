import {
    activeStep,
    currentTaskLabel,
    elapsedLabel,
    formatElapsed,
    isRunStale,
    isStreamLost,
    pendingQuestionLabel,
    prName,
    STALE_RUN_MAX_AGE_MS,
    STALE_RUN_SILENCE_MS,
} from './helpers'
import type { InstallationProgress, InstallationStep } from './installationProgressLogic'
import type { TaskRunConnectionStatus } from './taskRunStreamLogic'

const NOW = new Date('2026-01-01T12:00:00Z').getTime()
const iso = (msBeforeNow: number): string => new Date(NOW - msBeforeNow).toISOString()

describe('wizard-sync helpers', () => {
    it.each([
        ['m:ss under an hour', 125, '2:05'],
        ['h:mm:ss past the hour', 3725, '1:02:05'],
        ['clamps negatives to zero', -10, '0:00'],
        // The clock is driven by a persisted handle that outlives the run it names, so a run nobody
        // settled would otherwise count up for as long as the browser keeps the handle.
        ['clamps a runaway clock to the display cap', 42 * 3600, '6:00:00+'],
    ])('formatElapsed %s', (_name, seconds, expected) => {
        expect(formatElapsed(seconds)).toBe(expected)
    })

    it('elapsedLabel replaces a stale run clock with the reason it stopped mattering', () => {
        expect(elapsedLabel(125, false)).toBe('2:05')
        expect(elapsedLabel(125, true)).toBe('Stalled')
    })

    describe('isRunStale', () => {
        it.each([
            ['a run that just reported', iso(60_000), NOW - 60_000, true, false],
            [
                'a run silent past the window with no stream left',
                iso(60 * 60_000),
                NOW - STALE_RUN_SILENCE_MS - 1000,
                true,
                true,
            ],
            // The long agent phase and the 15 minute CI follow-up sleep both publish nothing. A run
            // whose stream is up is being watched, however little it has to say.
            [
                'a run silent past the window on a live stream',
                iso(60 * 60_000),
                NOW - STALE_RUN_SILENCE_MS - 1000,
                false,
                false,
            ],
            // No activity at all: the kickoff stamp is what the silence is measured from.
            ['a run that never reported, still inside the window', iso(60_000), null, true, false],
            ['a run that never reported, past the window', iso(STALE_RUN_SILENCE_MS + 1000), null, true, true],
            // The age cap is the second gate: a handle this old outlived a full day of reloads, so it
            // stands whatever the transport is doing.
            ['a fresh report on a day-old handle', iso(STALE_RUN_MAX_AGE_MS + 1000), NOW - 1000, false, true],
            // A legacy handle carries no kickoff stamp, so neither gate has anything to measure.
            ['a handle with no startedAt and no activity', undefined, null, true, false],
        ])('%s', (_name, startedAt, lastActivityAt, streamLost, expected) => {
            expect(isRunStale(startedAt, lastActivityAt, streamLost, NOW)).toBe(expected)
        })
    })

    describe('isStreamLost', () => {
        const cases: [string, TaskRunConnectionStatus, boolean, boolean][] = [
            ['an open stream is carrying updates', 'open', false, false],
            // Every mount of a long-lived run starts here, and so does every reconnect. Calling these
            // lost would stale a healthy run for the length of a connect and offer to dismiss it.
            ['a stream still connecting has not failed yet', 'connecting', false, false],
            ['a stream not yet started has not failed yet', 'idle', false, false],
            ['a failed stream is lost', 'error', false, true],
            ['a closed stream is lost', 'closed', false, true],
            // The stream that never gets past connecting: the run logic gives up after its own
            // window and says so here, so a permanently connecting stream is still reachable.
            ['a stream the logic gave up on is lost whatever it reports', 'connecting', true, true],
        ]
        it.each(cases)('%s', (_name, status, isStalled, expected) => {
            expect(isStreamLost(status, isStalled)).toBe(expected)
        })
    })

    it('activeStep prefers the wizard sub-step over the pipeline stage containing it', () => {
        // The card headline would otherwise read "Running setup wizard" while the wizard is
        // reporting something more specific like "Install SDK".
        const stage: InstallationStep = {
            id: 'setup:wizard',
            label: 'Running setup wizard',
            status: 'in_progress',
            detail: null,
        }
        const sub: InstallationStep = {
            id: 'wizard-task:a',
            label: 'Install SDK',
            status: 'in_progress',
            detail: null,
            source: 'wizard',
        }
        expect(activeStep([stage, sub])?.label).toBe('Install SDK')
        expect(activeStep([stage])?.label).toBe('Running setup wizard')
        expect(activeStep([])).toBeNull()
    })

    // The PR CTA interpolates this into the button label — a bad parse would render
    // "Review null" or leak a mangled identifier instead of falling back to "Review PR".
    it.each([
        ['https://github.com/acme-co/web/pull/42', 'acme-co/web#42'],
        ['https://github.com/acme-co/web/pull/42/files', 'acme-co/web#42'],
        ['https://github.com/acme-co/web/pull/42?diff=split', 'acme-co/web#42'],
        ['https://github.example.com/acme-co/web/pull/7', 'acme-co/web#7'],
        ['https://gitlab.com/acme-co/web/-/merge_requests/42', null],
        ['https://github.com/acme-co/web', null],
        ['not a url', null],
    ])('prName(%s) → %s', (url, expected) => {
        expect(prName(url)).toBe(expected)
    })

    describe('a pending question', () => {
        const withQuestion = (prompts: string[], sensitive = false): InstallationProgress =>
            ({
                phase: 'running',
                steps: [{ id: '1', label: 'Install the SDK', status: 'in_progress', detail: null }],
                error: null,
                prUrl: null,
                prMerged: false,
                isCurrent: true,
                pendingInput: { id: 'ask-1', askedAt: iso(0), questionCount: 1, sensitive, prompts },
            }) as InstallationProgress

        // The user is looking at the app, not the terminal, so the prominent line has to be the
        // instruction to go back there. Leading with the question buried that.
        it('leads with the call to action, not the question', () => {
            const progress = withQuestion(['Which region is your project in?'])
            expect(currentTaskLabel(progress)).toBe('Your terminal needs your attention')
            expect(currentTaskLabel(progress)).not.toContain('region')
        })

        it('carries the question separately, so it can render below the call to action', () => {
            expect(pendingQuestionLabel(withQuestion(['Which region is your project in?']))).toBe(
                'Which region is your project in?'
            )
        })

        it('has no question to show for a sensitive ask', () => {
            expect(pendingQuestionLabel(withQuestion([], true))).toBeNull()
            expect(currentTaskLabel(withQuestion([], true))).toBe('Your terminal needs your attention')
        })
    })
})
