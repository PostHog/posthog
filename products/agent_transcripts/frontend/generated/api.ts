import { apiMutator } from '../../../../frontend/src/lib/api-orval-mutator'
/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import type { CustomerSubmissionStateApi, PresignedUploadApi, StartUploadRequestApi } from './api.schemas'

export const getAgentTranscriptsCompleteUploadCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/agent_transcripts/complete_upload/`
}

/**
 * Step 2 of the upload: checks the uploaded file and sends it to review.
 */
export const agentTranscriptsCompleteUploadCreate = async (
    organizationId: string,
    options?: RequestInit
): Promise<CustomerSubmissionStateApi> => {
    return apiMutator<CustomerSubmissionStateApi>(getAgentTranscriptsCompleteUploadCreateUrl(organizationId), {
        ...options,
        method: 'POST',
    })
}

export const getAgentTranscriptsStartUploadCreateUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/agent_transcripts/start_upload/`
}

/**
 * Step 1 of the upload: returns a presigned POST to send the transcript file to. The file goes straight to storage. Call complete_upload once the POST succeeds.
 */
export const agentTranscriptsStartUploadCreate = async (
    organizationId: string,
    startUploadRequestApi: StartUploadRequestApi,
    options?: RequestInit
): Promise<PresignedUploadApi> => {
    return apiMutator<PresignedUploadApi>(getAgentTranscriptsStartUploadCreateUrl(organizationId), {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...options?.headers },
        body: JSON.stringify(startUploadRequestApi),
    })
}

export const getAgentTranscriptsSubmissionRetrieveUrl = (organizationId: string) => {
    return `/api/organizations/${organizationId}/agent_transcripts/submission/`
}

/**
 * The organization's transcript submission as its members see it.
 */
export const agentTranscriptsSubmissionRetrieve = async (
    organizationId: string,
    options?: RequestInit
): Promise<CustomerSubmissionStateApi> => {
    return apiMutator<CustomerSubmissionStateApi>(getAgentTranscriptsSubmissionRetrieveUrl(organizationId), {
        ...options,
        method: 'GET',
    })
}
