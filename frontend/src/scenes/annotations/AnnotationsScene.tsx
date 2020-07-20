import React from 'react'
import { AnnotationsTable } from './AnnotationsTable'
import { annotationsTableLogic } from './annotationsTableLogic'
import { hot } from 'react-hot-loader/root'

export const Annotations = hot(_Sessions)
function _Sessions(props) {
    return <AnnotationsTable {...props} logic={annotationsTableLogic} />
}
