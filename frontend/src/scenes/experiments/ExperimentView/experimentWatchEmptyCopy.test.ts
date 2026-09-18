import {
    type ExperimentWatchEmptyDeltas,
    type ExperimentWatchRunState,
    noSeparationShelfCopy,
    noStandoutBehaviorCaption,
    tooEarlyShelfCopy,
    underpoweredShelfCopy,
} from './experimentWatchEmptyCopy'

const COVERED = { from: 'May 30', to: 'Jun 1' }

const DELTAS: ExperimentWatchEmptyDeltas = {
    variants: [
        { key: 'control', persons: 190, sessions: 260 },
        { key: 'test', persons: 190, sessions: 255 },
    ],
    min_variant_persons: 50,
    sessions_truncated: false,
}

// Every sentence the shelf can end on, empty or not: the populated shelf's own caption makes the
// same promise when it has no finding to show.
const everyShelfSentence = (run: ExperimentWatchRunState): string[] => [
    tooEarlyShelfCopy(DELTAS, run, COVERED),
    underpoweredShelfCopy(DELTAS, run, COVERED),
    noSeparationShelfCopy(run),
    noStandoutBehaviorCaption(run),
]

const PROMISES_MORE_PEOPLE = /check back|can change as more people are exposed/i

describe('experiment watch empty copy', () => {
    // A paused or exposure-frozen experiment exposes nobody and has not ended, so `ended` is false
    // for it: the promise of more people reaches it through every branch that reads `ended` alone.
    // That is the regression here, and it is worst on the state that exists to say the comparison
    // is too small, because more people are exactly what it asks the reader to wait for.
    it.each([
        { state: 'running', run: { ended: false, enrolling: true, daysSinceStart: 30 }, promisesMore: true },
        {
            state: 'two days into its run',
            run: { ended: false, enrolling: true, daysSinceStart: 2 },
            promisesMore: true,
        },
        { state: 'paused', run: { ended: false, enrolling: false, daysSinceStart: 30 }, promisesMore: false },
        // Young and paused: the age lead must not put the promise back on its own.
        {
            state: 'paused two days in',
            run: { ended: false, enrolling: false, daysSinceStart: 2 },
            promisesMore: false,
        },
        { state: 'ended', run: { ended: true, enrolling: false, daysSinceStart: 30 }, promisesMore: false },
    ])('tells a reader to check back only while the experiment is $state: $promisesMore', ({ run, promisesMore }) => {
        for (const sentence of everyShelfSentence(run)) {
            expect(PROMISES_MORE_PEOPLE.test(sentence)).toBe(promisesMore)
        }
    })

    it('separates an experiment that stopped enrolling from one that is over', () => {
        // Both stop the promise, and only one of them is in the past tense. Reading "the experiment
        // ended" on a run the reader can resume would be wrong about what they have to do next.
        const paused: ExperimentWatchRunState = { ended: false, enrolling: false, daysSinceStart: 30 }
        const ended: ExperimentWatchRunState = { ended: true, enrolling: false, daysSinceStart: 30 }

        expect(underpoweredShelfCopy(DELTAS, paused, COVERED)).toContain('until the experiment is running again')
        expect(underpoweredShelfCopy(DELTAS, ended, COVERED)).toContain('not evidence that the variants behaved')
        expect(tooEarlyShelfCopy(DELTAS, paused, COVERED)).toContain('until the experiment is running again')
        expect(tooEarlyShelfCopy(DELTAS, ended, COVERED)).toContain('ended before enough people were exposed')
    })
})
