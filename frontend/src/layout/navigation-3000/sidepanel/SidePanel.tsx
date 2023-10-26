import { LemonButton } from '@posthog/lemon-ui'
import './SidePanel.scss'
import { IconNotebook, IconQuestion } from '@posthog/icons'

export function SidePanel(): JSX.Element {
    return (
        <nav className="SidePanel3000">
            <div className="SidePanel3000__content">
                <div className="SidePanel3000__top">
                    <div className="rotate-90 flex items-center gap-2 px-2">
                        <LemonButton icon={<IconNotebook className="rotate-270 w-6" />}>Notebooks</LemonButton>
                        <LemonButton icon={<IconQuestion className="rotate-270 w-6" />}>Feedback</LemonButton>
                    </div>
                </div>
            </div>
        </nav>
    )
}
