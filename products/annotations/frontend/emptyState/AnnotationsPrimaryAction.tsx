import { useActions } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { AnnotationModal } from 'scenes/annotations/AnnotationModal'
import { annotationModalLogic } from 'scenes/annotations/annotationModalLogic'

/**
 * Create button for the annotations empty state. Annotations are created in a modal
 * that the scene normally renders, and the gate replaces the scene - so the empty
 * state has to render the modal itself or the button would open nothing.
 */
export function AnnotationsPrimaryAction(): JSX.Element {
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    return (
        <>
            <LemonButton type="primary" onClick={() => openModalToCreateAnnotation()} data-attr="create-annotation">
                Create your first annotation
            </LemonButton>
            <AnnotationModal />
        </>
    )
}
