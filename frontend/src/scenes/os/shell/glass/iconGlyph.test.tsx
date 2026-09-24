import { render } from '@testing-library/react'
import { forwardRef } from 'react'

import { IconApp, IconGraph, IconGroups, IconRewindPlay } from '@posthog/icons'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { glyphFromSvg } from './iconGlyph'

// A production build strips function names, so an icon must not be recognized by its name.
const AnonymousIcon = forwardRef<SVGSVGElement>((props, ref) => (
    <svg ref={ref} viewBox="0 0 24 24" {...props}>
        <path d="M0 0h24v24H0z" />
    </svg>
))

function glyphOf(icon: JSX.Element): ReturnType<typeof glyphFromSvg> {
    const { container } = render(icon)
    return glyphFromSvg(container.querySelector('svg'))
}

describe('glyphFromSvg', () => {
    test.each([
        ['a plain icon', <IconGraph key="graph" />, 1],
        ['an icon drawn from several paths', <IconApp key="app" />, 3],
        ['a clipped group and its defs', <IconRewindPlay key="rewind" />, 1],
        ['a product icon inside its color wrapper', iconForType('product_analytics'), 1],
        ['an icon whose name the build stripped', <AnonymousIcon key="anonymous" />, 1],
    ])('turns %s into glass glyph parts', (_description, icon, expectedParts) => {
        const glyph = glyphOf(icon)

        expect(glyph?.viewBox).toBe('0 0 24 24')
        expect(glyph?.parts).toHaveLength(expectedParts)
        for (const part of glyph?.parts ?? []) {
            expect(part.d).toMatch(/^M/)
        }
    })

    it('keeps the fill rule, so cut-outs stay holes in the glass', () => {
        expect(glyphOf(<IconGroups />)?.parts[0].fillRule).toBe('evenodd')
    })

    test.each([
        ['no svg at all', <span key="span">A</span>],
        [
            'an svg with a shape the glass cannot trace',
            <svg key="svg" viewBox="0 0 24 24">
                <path d="M0 0h1v1H0z" />
                <circle r={4} />
            </svg>,
        ],
    ])('returns null for %s', (_description, icon) => {
        expect(glyphOf(icon)).toBeNull()
    })
})
