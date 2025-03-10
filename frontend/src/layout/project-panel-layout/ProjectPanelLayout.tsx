import { useActions, useValues } from "kea"
import { ProjectTree } from "~/layout/navigation-3000/components/ProjectTree/ProjectTree"
import { ProjectTreeNavbar } from "~/layout/navigation-3000/components/ProjectTree/ProjectTreeNavbar"
import { projectPanelLayoutLogic } from "./projectPanelLayoutLogic"
import { cva } from 'class-variance-authority'
import { cn } from "lib/utils/css-classes"
import { navigation3000Logic } from "../navigation-3000/navigationLogic"

const panelLayoutStyles = cva('grid gap-0 w-fit relative', {
    variants: {
        isPanelVisible: {
            true: 'grid-cols-[250px_1fr]',
            false: 'grid-cols-[250px_1fr]'
        },
        isPanelPinned: {
            true: '',
            false: ''
        }
    },
    compoundVariants: [
        {
            isPanelVisible: true,
            isPanelPinned: false,
            className: 'grid-cols-[250px_1fr]'
        },
        {
            isPanelVisible: true,
            isPanelPinned: true,
            className: 'grid-cols-[250px_1fr]'
        }
    ],
    defaultVariants: {
        isPanelPinned: false,
        isPanelVisible: false
    }
})

export function ProjectPanelLayout({ mainRef }: { mainRef: React.RefObject<HTMLElement> }): JSX.Element {
    const { isPanelPinned, isPanelVisible } = useValues(projectPanelLayoutLogic)
    const { mobileLayout } = useValues(navigation3000Logic)    
    const { togglePanelVisible } = useActions(projectPanelLayoutLogic)
    
    console.log('isPanelVisible', isPanelVisible)

    return (
        <div id="project-panel-layout" className={cn(panelLayoutStyles({ isPanelPinned, isPanelVisible }))}>
            <ProjectTreeNavbar />
            <div className={cn(
                "z-[var(--z-project-panel-layout)] h-screen",
                isPanelVisible ? 'block' : 'hidden',
                mobileLayout ? 'absolute left-[250px] top-0 bottom-0' : 'relative',
                !isPanelPinned ? 'absolute left-[250px] top-0 bottom-0' : 'relative'
            )}>
                <ProjectTree contentRef={mainRef} />
            </div>ekgirviuhbbhgukijhndufvhhrrfdgjvgfnu
            
            {!isPanelPinned && isPanelVisible && <div onClick={() => togglePanelVisible(!isPanelVisible)} className="z-[var(--z-project-panel-overlay)] fixed inset-0 w-screen h-screen"/>}
        </div>
    )
}
