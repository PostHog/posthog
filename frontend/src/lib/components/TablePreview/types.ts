export interface TablePreviewExtraColumn {
    key: string
    label: string
    type: string
}

export interface TablePreviewExpressionColumn extends TablePreviewExtraColumn {
    expression: string
}
