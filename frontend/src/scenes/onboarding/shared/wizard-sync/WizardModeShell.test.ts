import { wizardSupportsFramework } from './WizardModeShell'

describe('wizardSupportsFramework', () => {
    it.each([
        // Names the wizard lists directly.
        ['Ruby on Rails', true],
        ['Django', true],
        ['Python', true],
        ['React', true],
        // Names SDK pages pass that alias to a listed framework.
        ['Svelte', true],
        ['Swift', true],
        ['Nuxt 3.7+', true],
        ['Nuxt 3.6 and below', true],
        // Case and spacing do not matter.
        ['  django  ', true],
        // Frameworks the wizard does not set up — the badge row must hide, not show a list that omits them.
        ['Ruby', false],
        ['Hono', false],
        ['Node.js', false],
        ['Kotlin Multiplatform', false],
        ['TanStack Start', false],
        ['JavaScript Web', false],
    ])('%s -> %s', (integrationName, expected) => {
        expect(wizardSupportsFramework(integrationName)).toBe(expected)
    })
})
