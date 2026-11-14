import { useActions } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { annotationModalLogic } from '../logics/annotationModalLogic'

export function AnnotationsPrimaryAction(): JSX.Element {
    const { openModalToCreateAnnotation } = useActions(annotationModalLogic)

    return (
        <LemonButton type="primary" onClick={() => openModalToCreateAnnotation()} data-attr="create-annotation">
            Create your first annotation
        </LemonButton>
    )
}
