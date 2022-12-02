import { useActions, useValues } from 'kea'
import { IconUploadFile } from 'lib/components/icons'
import Dragger from 'antd/lib/upload/Dragger'
import { importSessionRecordingLogic } from './importSessionRecordingLogic'
import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { AlertMessage } from 'lib/components/AlertMessage'

export function ImportSessionRecording(): JSX.Element {
    const { loadFromFile, resetSessionRecording } = useActions(importSessionRecordingLogic)
    const { sessionRecording, sessionRecordingLoading } = useValues(importSessionRecordingLogic)

    return (
        <div>
            {sessionRecordingLoading ? (
                <SpinnerOverlay />
            ) : sessionRecording ? (
                <div className="space-y-2">
                    <AlertMessage
                        type="info"
                        action={{
                            onClick: () => resetSessionRecording(),
                            children: 'Import a different recording',
                        }}
                    >
                        You are viewing a recording imported from a file.
                    </AlertMessage>
                    <SessionRecordingPlayer sessionRecordingData={sessionRecording} playerKey={`importer`} />
                </div>
            ) : (
                <Dragger
                    name="file"
                    multiple={false}
                    // fileList={}
                    accept=".json"
                    showUploadList={false}
                    className="dragger2"
                    beforeUpload={(file) => {
                        loadFromFile(file)
                        return false
                    }}
                >
                    {/* {cohort.csv ? (
                        <>
                            <IconUploadFile style={{ fontSize: '3rem', color: 'var(--muted-alt)' }} />
                            <div className="ant-upload-text">{cohort.csv?.name ?? 'File chosen'}</div>
                        </>
                    ) : (
                        <>
                            <IconUploadFile style={{ fontSize: '3rem', color: 'var(--muted-alt)' }} />
                            <div className="ant-upload-text">Drag a file here or click to browse for a file</div>
                        </>
                    )} */}

                    <div className="p-20 flex flex-col items-center justify-center space-y-2 text-muted-alt">
                        <p className="flex items-center gap-2 font-semibold uppercase">
                            <IconUploadFile className="text-xl" />
                            Import file
                        </p>
                        <p className="text-muted-alt ">
                            Drag and drop your exported recording here or click to open the file browser.
                        </p>
                    </div>
                </Dragger>
            )}
        </div>
    )
}
