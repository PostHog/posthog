import { LemonButton } from '@posthog/lemon-ui'
import './SidePanel.scss'
import { IconComment, IconNotebook } from 'lib/lemon-ui/icons'

export function SidePanel(): JSX.Element {
    return (
        <nav className="SidePanel3000">
            <div className="SidePanel3000__content">
                <div className="SidePanel3000__top">
                    <div className="rotate-90 flex items-center gap-2 px-2">
                        <LemonButton icon={<IconNotebook className="rotate-270" />}>Notebooks</LemonButton>
                        <LemonButton icon={<IconComment className="rotate-270" />}>Feedback</LemonButton>
                    </div>
                </div>
            </div>
        </nav>
    )
}
