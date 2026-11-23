import { Badge, Spinner } from '@posthog/quill'

export function QuillUploadedFiles({ files, loading }: { files: File[]; loading: boolean | undefined }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-2">
            {files.map((file, index) => (
                <Badge key={index}>
                    {loading && <Spinner />}
                    <span className="truncate">{file.name}</span>
                </Badge>
            ))}
        </div>
    )
}
