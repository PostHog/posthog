import { render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { IngestionWarning } from './ingestionWarningsLogic'
import { WARNING_TYPE_RENDERER } from './IngestionWarningsView'

/**
 * Models what Chrome's and Edge's in-page translation actually do to the DOM: every translatable
 * text node is replaced by a `<font>` element holding the translated text, and `translate="no"`
 * subtrees are left alone. React keeps pointing at the original node, so updating or removing it
 * later writes to a detached node or throws `NotFoundError` (react#11538).
 */
function simulatePageTranslation(root: HTMLElement): void {
    const walk = (node: Node): void => {
        if (node.nodeType === Node.ELEMENT_NODE && (node as HTMLElement).getAttribute('translate') === 'no') {
            return
        }
        for (const child of Array.from(node.childNodes)) {
            if (child.nodeType === Node.TEXT_NODE && child.textContent?.trim()) {
                const translated = document.createElement('font')
                translated.textContent = `翻译:${child.textContent}`
                node.replaceChild(translated, child)
            } else {
                walk(child)
            }
        }
    }
    walk(root)
}

describe('WARNING_TYPE_RENDERER', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // The table gives its rows positional keys, so sorting or searching while a group is expanded
    // feeds a different warning to a mounted row instead of remounting it.
    const Host = ({ warning }: { warning: IngestionWarning }): JSX.Element => (
        <div>{WARNING_TYPE_RENDERER[warning.type as keyof typeof WARNING_TYPE_RENDERER](warning)}</div>
    )

    it('shows the new durations when a translated too-old row is reused', () => {
        const warning = (ageInSeconds: number): IngestionWarning => ({
            type: 'event_dropped_too_old',
            timestamp: '2026-03-04T10:00:00Z',
            details: {
                eventUuid: '0195b1f0-0000-7000-8000-000000000001',
                event: 'signed_up',
                distinctId: 'user-1',
                eventTimestamp: '2026-03-04T09:00:00Z',
                ageInSeconds,
                dropThresholdSeconds: 604800,
            },
        })

        const { container, rerender } = render(<Host warning={warning(7200)} />)
        simulatePageTranslation(container)

        rerender(<Host warning={warning(86400)} />)

        expect(container.textContent).toContain('1d')
        expect(container.textContent).not.toContain('2h')
    })

    it('survives a translated transformation row gaining a link', () => {
        const warning = (transformationId?: string): IngestionWarning => ({
            type: 'event_dropped_by_transformation',
            timestamp: '2026-03-04T10:00:00Z',
            details: {
                eventUuid: '0195b1f0-0000-7000-8000-000000000002',
                event: 'signed_up',
                distinctId: 'user-1',
                transformationId,
                transformationName: transformationId ? 'Drop test traffic' : undefined,
            },
        })

        const { container, rerender } = render(<Host warning={warning()} />)
        simulatePageTranslation(container)

        expect(() => rerender(<Host warning={warning('0195b1f0-0000-7000-8000-000000000003')} />)).not.toThrow()
    })
})
