import { ASSISTANT_NAVIGATE_URLS, AssistantNavigateUrl } from '../../../queries/schema/schema-assistant-messages'
import { buildSceneDescriptionsContext } from './sceneDescriptionsContext'

describe('buildSceneDescriptionsContext', () => {
    it('returns a string with scene descriptions', () => {
        const result = buildSceneDescriptionsContext()
        expect(typeof result).toBe('string')
    })

    it('includes scene descriptions for pages that have them', () => {
        const result = buildSceneDescriptionsContext()
        // Check for pages with descriptions in sceneConfigurations
        expect(result).toContain('cohorts')
        expect(result).toContain('A catalog of identified persons')
        expect(result).toContain('insights')
    })

    it('includes tools available on specific scenes', () => {
        const result = buildSceneDescriptionsContext()
        // Tools that are product-specific should be listed
        expect(result).toContain('[tools:')
        // Check for specific known tools
        expect(result).toContain('Edit the insight')
        expect(result).toContain('Search recordings')
    })

    it('excludes pages without descriptions or tools', () => {
        const result = buildSceneDescriptionsContext()
        const lines = result.split('\n')
        // Every non-empty line should either have a description (colon after key) or tools
        for (const line of lines) {
            if (line.trim()) {
                const afterKey = line.substring(line.indexOf('**') + 2)
                const hasDescriptionOrTools = afterKey.includes(':') || afterKey.includes('[tools:')
                expect(hasDescriptionOrTools).toBe(true)
            }
        }
    })

    it('formats entries correctly with markdown bold', () => {
        const result = buildSceneDescriptionsContext()
        const lines = result.split('\n').filter((l) => l.trim())
        // Each line should start with "- **" and have a closing "**"
        for (const line of lines) {
            expect(line).toMatch(/^- \*\*\w+\*\*/)
        }
    })

    it('handles URL functions that require parameters gracefully', () => {
        // Some URL functions require parameters, these should be caught and skipped
        const result = buildSceneDescriptionsContext()
        // Should not throw and should return a valid string with content
        expect(typeof result).toBe('string')
        expect(result.length).toBeGreaterThan(0)
    })

    it('does not include parameterized route patterns', () => {
        const result = buildSceneDescriptionsContext()
        // Should not include URL parameter patterns like :id, :teamId, etc.
        expect(result).not.toMatch(/:id/)
        expect(result).not.toMatch(/:teamId/)
        expect(result).not.toMatch(/:\w+/)
    })

    it('includes specific scene keys with their tools', () => {
        const result = buildSceneDescriptionsContext()

        // Scene.Insight - should include Edit the insight tool
        expect(result).toContain('insightNew')
        expect(result).toContain('Edit the insight')

        // Scene.Replay - should include Search recordings tool
        expect(result).toContain('replay')
        expect(result).toContain('Search recordings')

        // Scene.SQLEditor - should include Write and tweak SQL tool
        expect(result).toContain('sqlEditor')
        expect(result).toContain('Write and tweak SQL')

        // Scene.Surveys - should include Create surveys and Analyze survey responses tools
        expect(result).toContain('surveys')
        expect(result).toContain('Create surveys')
        expect(result).toContain('Analyze survey responses')
    })

    it('includes scenes with multiple tools correctly formatted', () => {
        const result = buildSceneDescriptionsContext()

        // ErrorTracking has multiple tools
        const errorTrackingLine = result.split('\n').find((line) => line.includes('errorTracking'))
        expect(errorTrackingLine).toBeTruthy()
        expect(errorTrackingLine).toContain('[tools:')
        expect(errorTrackingLine).toContain('Filter issues')
        expect(errorTrackingLine).toContain('Find impactful issues')

        // Surveys has multiple tools
        const surveysLine = result.split('\n').find((line) => line.includes('surveys'))
        expect(surveysLine).toBeTruthy()
        expect(surveysLine).toContain('[tools:')
        expect(surveysLine).toContain('Create surveys')
        expect(surveysLine).toContain('Analyze survey responses')
    })

    it('includes specific navigable scene keys without requiring parameters', () => {
        const result = buildSceneDescriptionsContext()

        // Verify key scenes are present (only those that don't require parameters)
        expect(result).toContain('cohorts')
        expect(result).toContain('featureFlags')
        expect(result).toContain('persons')
        expect(result).toContain('notebooks')
        expect(result).toContain('insights')
    })

    it('correctly maps tools to their respective scenes', () => {
        const result = buildSceneDescriptionsContext()

        // Verify tools are listed with the correct scenes
        const lines = result.split('\n')

        // RevenueAnalytics should have Filter revenue analytics tool
        const revenueAnalyticsLine = lines.find((line) => line.includes('revenueAnalytics'))
        if (revenueAnalyticsLine) {
            expect(revenueAnalyticsLine).toContain('Filter revenue analytics')
        }

        // DataPipelines tools
        // Note: DataPipelines is a scene but may not have a simple URL function without params

        // UserInterviews should have Analyze user interviews tool
        const userInterviewsLine = lines.find((line) => line.includes('userInterviews'))
        if (userInterviewsLine) {
            expect(userInterviewsLine).toContain('Analyze user interviews')
        }
    })

    it('only includes URL keys that are in AssistantNavigateUrl', () => {
        const result = buildSceneDescriptionsContext()
        const lines = result.split('\n').filter((l) => l.trim())

        // Extract URL keys from each line (between - ** and **)
        for (const line of lines) {
            const match = line.match(/^- \*\*(\w+)\*\*/)
            expect(match).toBeTruthy()
            if (match) {
                const urlKey = match[1]
                expect(ASSISTANT_NAVIGATE_URLS.has(urlKey as AssistantNavigateUrl)).toBe(true)
            }
        }
    })

    it('all returned URL keys are valid entries in AssistantNavigateUrl', () => {
        const result = buildSceneDescriptionsContext()
        const lines = result.split('\n').filter((l) => l.trim())

        // Build set of all URL keys in the output
        const outputUrlKeys = new Set<string>()
        for (const line of lines) {
            const match = line.match(/^- \*\*(\w+)\*\*/)
            if (match) {
                outputUrlKeys.add(match[1])
            }
        }

        // Verify every URL key in output is in ASSISTANT_NAVIGATE_URLS
        for (const urlKey of outputUrlKeys) {
            expect(ASSISTANT_NAVIGATE_URLS.has(urlKey as AssistantNavigateUrl)).toBe(true)
        }

        // Verify we have at least some keys
        expect(outputUrlKeys.size).toBeGreaterThan(0)
    })
})
