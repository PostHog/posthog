import './TopBar.scss'

import { CommandPalette } from 'lib/components/CommandPalette/CommandPalette'

import { Announcement } from './Announcement'

export function TopBar(): JSX.Element {
    return (
        <>
            <Announcement />
            <CommandPalette />
        </>
    )
}
