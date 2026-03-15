import { validateInput } from '../recorder'
import { RasterizeRecordingInput } from '../types'

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session-123',
        team_id: 1,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

describe('validateInput', () => {
    it('accepts valid input', () => {
        expect(() => validateInput(baseInput())).not.toThrow()
    })

    it.each([
        { field: 'playback_speed', value: 0, error: 'playback_speed must be positive' },
        { field: 'playback_speed', value: -1, error: 'playback_speed must be positive' },
        { field: 'capture_timeout', value: 0, error: 'capture_timeout must be positive' },
        { field: 'capture_timeout', value: -5, error: 'capture_timeout must be positive' },
        { field: 'recording_fps', value: 0, error: 'recording_fps must be positive' },
        { field: 'recording_fps', value: -10, error: 'recording_fps must be positive' },
        { field: 'trim', value: 0, error: 'trim must be positive' },
        { field: 'trim', value: -5, error: 'trim must be positive' },
    ])('rejects $field=$value', ({ field, value, error }) => {
        expect(() => validateInput(baseInput({ [field]: value }))).toThrow(error)
    })

    it('rejects empty session_id', () => {
        expect(() => validateInput(baseInput({ session_id: '' }))).toThrow('session_id is required')
    })

    it('rejects invalid team_id', () => {
        expect(() => validateInput(baseInput({ team_id: 0 }))).toThrow('team_id must be a positive integer')
        expect(() => validateInput(baseInput({ team_id: -1 }))).toThrow('team_id must be a positive integer')
    })
})
