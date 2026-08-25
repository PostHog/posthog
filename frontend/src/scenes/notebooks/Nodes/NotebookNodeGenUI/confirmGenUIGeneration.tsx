import { LemonDialog } from '@posthog/lemon-ui'

export function confirmGenUIGeneration(generate: () => void): void {
    LemonDialog.open({
        title: 'Regenerate visualization?',
        content:
            'This generates new visualization code and uses AI credits. Reload data instead if only the results changed.',
        primaryButton: {
            children: 'Regenerate',
            onClick: generate,
        },
        secondaryButton: { children: 'Cancel' },
    })
}
