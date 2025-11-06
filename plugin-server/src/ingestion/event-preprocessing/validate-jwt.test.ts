import * as jwt from 'jsonwebtoken'

import { EventHeaders, IncomingEventWithTeam, JwtVerificationStatus, Team } from '../../types'
import { TeamSecretKey, TeamSecretKeysManager } from '../../utils/team-secret-keys-manager'
import { drop, ok } from '../pipelines/results'
import { createValidateJwtStep } from './validate-jwt'

describe('createValidateJwtStep', () => {
    let mockTeamSecretKeysManager: jest.Mocked<TeamSecretKeysManager>
    let step: ReturnType<typeof createValidateJwtStep>

    const mockTeam: Team = {
        id: 1,
        project_id: 1 as any,
        uuid: 'team-uuid',
        organization_id: 'org-1',
        name: 'Test Team',
        anonymize_ips: false,
        api_token: 'test-token',
        slack_incoming_webhook: null,
        session_recording_opt_in: false,
        person_processing_opt_out: false,
        heatmaps_opt_in: false,
        ingested_event: false,
        person_display_name_properties: null,
        test_account_filters: null,
        cookieless_server_hash_mode: null,
        timezone: 'UTC',
        available_features: [],
        drop_events_older_than_seconds: null,
        verify_events: 'accept_all',
    }

    const mockEventWithTeam: IncomingEventWithTeam = {
        message: {} as any,
        event: {
            event: '$pageview',
            distinct_id: 'user123',
            team_id: 1,
        } as any,
        team: mockTeam,
        headers: {
            force_disable_person_processing: false,
        },
    }

    beforeEach(() => {
        mockTeamSecretKeysManager = {
            getSecretKey: jest.fn(),
        } as any

        step = createValidateJwtStep(mockTeamSecretKeysManager)
    })

    it('should return verified=NotVerified when no JWT is provided', async () => {
        const input = {
            headers: {
                force_disable_person_processing: false,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.NotVerified,
            })
        )
        expect(mockTeamSecretKeysManager.getSecretKey).not.toHaveBeenCalled()
    })

    it('should return verified=Invalid when JWT cannot be decoded', async () => {
        const input = {
            headers: {
                jwt: 'invalid-jwt-token',
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Invalid,
            })
        )
        expect(mockTeamSecretKeysManager.getSecretKey).not.toHaveBeenCalled()
    })

    it('should return verified=Invalid when JWT header is missing kid', async () => {
        const secret = 'test-secret'
        const token = jwt.sign({ data: 'test' }, secret, { algorithm: 'HS256' })

        const input = {
            headers: {
                jwt: token,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Invalid,
            })
        )
        expect(mockTeamSecretKeysManager.getSecretKey).not.toHaveBeenCalled()
    })

    it('should return verified=Invalid when secret key is not found', async () => {
        const secret = 'test-secret'
        const token = jwt.sign({ data: 'test' }, secret, { algorithm: 'HS256', keyid: 'phsk_test_abc123' })

        mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(null)

        const input = {
            headers: {
                jwt: token,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Invalid,
            })
        )
        expect(mockTeamSecretKeysManager.getSecretKey).toHaveBeenCalledWith('phsk_test_abc123')
    })

    it('should return verified=Invalid when secret key belongs to different team', async () => {
        const secret = 'phs_test_secret123'
        const token = jwt.sign({ data: 'test' }, secret, { algorithm: 'HS256', keyid: 'phsk_test_abc123' })

        const mockSecretKey: TeamSecretKey = {
            id: 'phsk_test_abc123',
            team_id: 2, // Different team
            name: 'Test Key',
            secure_value: secret,
            created_at: '2023-01-01T00:00:00Z',
            last_used_at: null,
        }

        mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

        const input = {
            headers: {
                jwt: token,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Invalid,
            })
        )
        expect(mockTeamSecretKeysManager.getSecretKey).toHaveBeenCalledWith('phsk_test_abc123')
    })

    it('should return verified=Invalid when JWT signature is invalid', async () => {
        const secret = 'phs_test_secret123'
        const wrongSecret = 'phs_wrong_secret456'
        const token = jwt.sign({ data: 'test' }, wrongSecret, { algorithm: 'HS256', keyid: 'phsk_test_abc123' })

        const mockSecretKey: TeamSecretKey = {
            id: 'phsk_test_abc123',
            team_id: 1,
            name: 'Test Key',
            secure_value: secret,
            created_at: '2023-01-01T00:00:00Z',
            last_used_at: null,
        }

        mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

        const input = {
            headers: {
                jwt: token,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Invalid,
            })
        )
    })

    it('should return verified=Verified when JWT is valid with matching distinct_id', async () => {
        const secret = 'phs_test_secret123'
        const token = jwt.sign({ data: 'test', distinct_id: 'user123' }, secret, {
            algorithm: 'HS256',
            keyid: 'phsk_test_abc123',
        })

        const mockSecretKey: TeamSecretKey = {
            id: 'phsk_test_abc123',
            team_id: 1,
            name: 'Test Key',
            secure_value: secret,
            created_at: '2023-01-01T00:00:00Z',
            last_used_at: null,
        }

        mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

        const input = {
            headers: {
                jwt: token,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Verified,
            })
        )
        expect(mockTeamSecretKeysManager.getSecretKey).toHaveBeenCalledWith('phsk_test_abc123')
    })

    it('should support HS512 algorithm', async () => {
        const secret = 'phs_test_secret123'
        const token = jwt.sign({ data: 'test', distinct_id: 'user123' }, secret, {
            algorithm: 'HS512',
            keyid: 'phsk_test_abc123',
        })

        const mockSecretKey: TeamSecretKey = {
            id: 'phsk_test_abc123',
            team_id: 1,
            name: 'Test Key',
            secure_value: secret,
            created_at: '2023-01-01T00:00:00Z',
            last_used_at: null,
        }

        mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

        const input = {
            headers: {
                jwt: token,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Verified,
            })
        )
    })

    it('should preserve additional input properties', async () => {
        const input = {
            headers: {
                force_disable_person_processing: false,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
            customField: 'custom-value',
            anotherField: 42,
        } as any

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.NotVerified,
            })
        )
    })

    it('should return verified=Invalid when an unexpected error occurs', async () => {
        const secret = 'phs_test_secret123'
        const token = jwt.sign({ data: 'test' }, secret, { algorithm: 'HS256', keyid: 'phsk_test_abc123' })

        mockTeamSecretKeysManager.getSecretKey.mockRejectedValue(new Error('Database error'))

        const input = {
            headers: {
                jwt: token,
            } as EventHeaders,
            eventWithTeam: mockEventWithTeam,
        }

        const result = await step(input)

        expect(result).toEqual(
            ok({
                ...input,
                verified: JwtVerificationStatus.Invalid,
            })
        )
    })

    describe('distinct_id validation', () => {
        it('should return verified=Invalid when JWT is missing distinct_id claim', async () => {
            const secret = 'phs_test_secret123'
            const token = jwt.sign({ data: 'test' }, secret, { algorithm: 'HS256', keyid: 'phsk_test_abc123' })

            const mockSecretKey: TeamSecretKey = {
                id: 'phsk_test_abc123',
                team_id: 1,
                name: 'Test Key',
                secure_value: secret,
                created_at: '2023-01-01T00:00:00Z',
                last_used_at: null,
            }

            mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

            const input = {
                headers: {
                    jwt: token,
                } as EventHeaders,
                eventWithTeam: mockEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    verified: JwtVerificationStatus.Invalid,
                })
            )
        })

        it('should return verified=Invalid when JWT distinct_id does not match event distinct_id', async () => {
            const secret = 'phs_test_secret123'
            const token = jwt.sign({ data: 'test', distinct_id: 'different_user' }, secret, {
                algorithm: 'HS256',
                keyid: 'phsk_test_abc123',
            })

            const mockSecretKey: TeamSecretKey = {
                id: 'phsk_test_abc123',
                team_id: 1,
                name: 'Test Key',
                secure_value: secret,
                created_at: '2023-01-01T00:00:00Z',
                last_used_at: null,
            }

            mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

            const input = {
                headers: {
                    jwt: token,
                } as EventHeaders,
                eventWithTeam: mockEventWithTeam,
            }

            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    verified: JwtVerificationStatus.Invalid,
                })
            )
        })
    })

    describe('verify_events modes', () => {
        it('should drop event when verify_events=reject_invalid and JWT is invalid', async () => {
            const secret = 'phs_test_secret123'
            const wrongSecret = 'phs_wrong_secret456'
            const token = jwt.sign({ data: 'test', distinct_id: 'user123' }, wrongSecret, {
                algorithm: 'HS256',
                keyid: 'phsk_test_abc123',
            })

            const mockSecretKey: TeamSecretKey = {
                id: 'phsk_test_abc123',
                team_id: 1,
                name: 'Test Key',
                secure_value: secret,
                created_at: '2023-01-01T00:00:00Z',
                last_used_at: null,
            }

            mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

            const teamWithRejectInvalid = {
                ...mockEventWithTeam,
                team: { ...mockTeam, verify_events: 'reject_invalid' as const },
            }

            const input = {
                headers: {
                    jwt: token,
                } as EventHeaders,
                eventWithTeam: teamWithRejectInvalid,
            }

            const result = await step(input)

            expect(result).toEqual(drop('jwt_invalid'))
        })

        it('should accept unverified event when verify_events=reject_invalid', async () => {
            const teamWithRejectInvalid = {
                ...mockEventWithTeam,
                team: { ...mockTeam, verify_events: 'reject_invalid' as const },
            }

            const input = {
                headers: {
                    force_disable_person_processing: false,
                } as EventHeaders,
                eventWithTeam: teamWithRejectInvalid,
            }

            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    verified: JwtVerificationStatus.NotVerified,
                })
            )
        })

        it('should drop event when verify_events=reject_unverified and event has no JWT', async () => {
            const teamWithRejectUnverified = {
                ...mockEventWithTeam,
                team: { ...mockTeam, verify_events: 'reject_unverified' as const },
            }

            const input = {
                headers: {
                    force_disable_person_processing: false,
                } as EventHeaders,
                eventWithTeam: teamWithRejectUnverified,
            }

            const result = await step(input)

            expect(result).toEqual(drop('jwt_not_verified'))
        })

        it('should drop event when verify_events=reject_unverified and JWT is invalid', async () => {
            const secret = 'phs_test_secret123'
            const wrongSecret = 'phs_wrong_secret456'
            const token = jwt.sign({ data: 'test', distinct_id: 'user123' }, wrongSecret, {
                algorithm: 'HS256',
                keyid: 'phsk_test_abc123',
            })

            const mockSecretKey: TeamSecretKey = {
                id: 'phsk_test_abc123',
                team_id: 1,
                name: 'Test Key',
                secure_value: secret,
                created_at: '2023-01-01T00:00:00Z',
                last_used_at: null,
            }

            mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

            const teamWithRejectUnverified = {
                ...mockEventWithTeam,
                team: { ...mockTeam, verify_events: 'reject_unverified' as const },
            }

            const input = {
                headers: {
                    jwt: token,
                } as EventHeaders,
                eventWithTeam: teamWithRejectUnverified,
            }

            const result = await step(input)

            expect(result).toEqual(drop('jwt_not_verified'))
        })

        it('should accept verified event when verify_events=reject_unverified', async () => {
            const secret = 'phs_test_secret123'
            const token = jwt.sign({ data: 'test', distinct_id: 'user123' }, secret, {
                algorithm: 'HS256',
                keyid: 'phsk_test_abc123',
            })

            const mockSecretKey: TeamSecretKey = {
                id: 'phsk_test_abc123',
                team_id: 1,
                name: 'Test Key',
                secure_value: secret,
                created_at: '2023-01-01T00:00:00Z',
                last_used_at: null,
            }

            mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

            const teamWithRejectUnverified = {
                ...mockEventWithTeam,
                team: { ...mockTeam, verify_events: 'reject_unverified' as const },
            }

            const input = {
                headers: {
                    jwt: token,
                } as EventHeaders,
                eventWithTeam: teamWithRejectUnverified,
            }

            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    verified: JwtVerificationStatus.Verified,
                })
            )
        })

        it('should accept all events when verify_events=accept_all (default)', async () => {
            const secret = 'phs_test_secret123'
            const wrongSecret = 'phs_wrong_secret456'
            const token = jwt.sign({ data: 'test', distinct_id: 'user123' }, wrongSecret, {
                algorithm: 'HS256',
                keyid: 'phsk_test_abc123',
            })

            const mockSecretKey: TeamSecretKey = {
                id: 'phsk_test_abc123',
                team_id: 1,
                name: 'Test Key',
                secure_value: secret,
                created_at: '2023-01-01T00:00:00Z',
                last_used_at: null,
            }

            mockTeamSecretKeysManager.getSecretKey.mockResolvedValue(mockSecretKey)

            const input = {
                headers: {
                    jwt: token,
                } as EventHeaders,
                eventWithTeam: mockEventWithTeam, // Uses default accept_all
            }

            const result = await step(input)

            expect(result).toEqual(
                ok({
                    ...input,
                    verified: JwtVerificationStatus.Invalid,
                })
            )
        })
    })
})
