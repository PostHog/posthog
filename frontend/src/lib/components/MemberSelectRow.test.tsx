import { MOCK_DEFAULT_ORGANIZATION_MEMBER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, RenderResult, screen } from '@testing-library/react'

import { fullName } from 'lib/utils/strings'

import { MemberSelectRow, MemberSelectRowProps } from './MemberSelectRow'

describe('MemberSelectRow', () => {
    const member = MOCK_DEFAULT_ORGANIZATION_MEMBER

    afterEach(() => {
        cleanup()
    })

    function renderRow(props: Partial<MemberSelectRowProps> = {}): RenderResult {
        return render(
            <ul>
                <MemberSelectRow member={member} isYou={false} onClick={jest.fn()} {...props} />
            </ul>
        )
    }

    it('renders the member name', () => {
        renderRow()
        expect(screen.getByText(fullName(member.user))).toBeInTheDocument()
    })

    it.each([
        ['shows', true],
        ['hides', false],
    ])('%s the "(you)" label according to isYou', (_, isYou) => {
        renderRow({ isYou })
        if (isYou) {
            expect(screen.getByText('(you)')).toBeInTheDocument()
        } else {
            expect(screen.queryByText('(you)')).not.toBeInTheDocument()
        }
    })

    it('renders no checkbox for a single-select row (`checked` omitted)', () => {
        const { container } = renderRow()
        expect(container.querySelector('input[type="checkbox"]')).toBeNull()
    })

    it.each([
        ['checked', true],
        ['unchecked', false],
    ])('renders a %s checkbox for a multi-select row', (_, checked) => {
        const { container } = renderRow({ checked })
        const checkbox = container.querySelector('input[type="checkbox"]') as HTMLInputElement | null
        expect(checkbox).not.toBeNull()
        expect(checkbox!.checked).toBe(checked)
    })

    it('fires onClick when the row is clicked', () => {
        const onClick = jest.fn()
        renderRow({ onClick })
        fireEvent.click(screen.getByText(fullName(member.user)))
        expect(onClick).toHaveBeenCalledTimes(1)
    })
})
