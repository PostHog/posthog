import { SceneSection } from '~/layout/scenes/components/SceneSection'

export interface ServiceSectionProps {
    id: string
    title: string
    children: React.ReactNode
}

/** One block of the service page, with the anchor its table of contents scrolls to. */
export function ServiceSection({ id, title, children }: ServiceSectionProps): JSX.Element {
    return (
        <div id={id} className="scroll-mt-4">
            <SceneSection title={title}>{children}</SceneSection>
        </div>
    )
}
