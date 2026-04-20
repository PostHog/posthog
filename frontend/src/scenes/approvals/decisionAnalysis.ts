import { ApprovalDecision, ChangeRequest, ChangeRequestState, DecisionAnalysis } from '~/types'

/**
 * Generate human-readable decision analysis based on change request state and approvals.
 *
 * This function analyzes the current state of a change request and generates
 * a human-readable explanation of the decision, including vote counts and reasoning.
 *
 * @param changeRequest - The change request to analyze
 * @returns DecisionAnalysis object with summary, details, and vote counts
 */
export function generateDecisionAnalysis(changeRequest: ChangeRequest): DecisionAnalysis {
    const approvals = changeRequest.approvals || []
    const approvedCount = approvals.filter((a) => a.decision === ApprovalDecision.Approved).length
    const rejectedCount = approvals.filter((a) => a.decision === ApprovalDecision.Rejected).length
    const totalVotes = approvals.length

    const quorum = changeRequest.policy_snapshot?.quorum || 1

    // Get voter names
    const approvedBy = approvals
        .filter((a) => a.decision === ApprovalDecision.Approved)
        .map((a) => a.created_by.first_name || a.created_by.email)
    const rejectedBy = approvals
        .filter((a) => a.decision === ApprovalDecision.Rejected)
        .map((a) => a.created_by.first_name || a.created_by.email)

    const analysis: DecisionAnalysis = {
        status: changeRequest.state,
        summary: '',
        details: '',
        votes: {
            approved: approvedCount,
            rejected: rejectedCount,
            total: totalVotes,
            quorum: quorum,
        },
    }

    // Generate state-specific analysis
    switch (changeRequest.state) {
        case ChangeRequestState.Pending:
            if (totalVotes === 0) {
                analysis.summary = `Awaiting approval from ${quorum} approver${quorum > 1 ? 's' : ''}`
                analysis.details = `This change request requires ${quorum} approval${quorum > 1 ? 's' : ''} to be applied. No votes have been cast yet.`
            } else {
                analysis.summary = `${approvedCount}/${quorum} approvals received, ${rejectedCount} rejection${rejectedCount !== 1 ? 's' : ''}`
                const detailsParts: string[] = []
                if (approvedCount > 0) {
                    detailsParts.push(`✓ Approved by: ${approvedBy.join(', ')}`)
                }
                if (rejectedCount > 0) {
                    detailsParts.push(`✗ Rejected by: ${rejectedBy.join(', ')}`)
                }
                const remaining = quorum - approvedCount
                if (remaining > 0) {
                    detailsParts.push(
                        `\nRequires ${remaining} more approval${remaining !== 1 ? 's' : ''} to be applied automatically.`
                    )
                } else {
                    detailsParts.push(`\nReached the required ${quorum} approval${quorum > 1 ? 's' : ''}.`)
                }
                analysis.details = detailsParts.join('\n')
            }
            break

        case ChangeRequestState.Rejected:
            if (rejectedCount > 0) {
                analysis.summary = `Rejected by ${rejectedBy.join(', ')}`
                analysis.details = `This change request was rejected and will not be applied.

Final vote count:
✗ Rejected: ${rejectedCount} (${rejectedBy.join(', ')})
✓ Approved: ${approvedCount}${approvedBy.length > 0 ? ` (${approvedBy.join(', ')})` : ''}
Required quorum: ${quorum}

Note: A single rejection immediately rejects the entire change request, regardless of the number of approvals.`
            } else {
                // Canceled by requester
                analysis.summary = 'Canceled by requester'
                analysis.details = 'This change request was canceled by the requester and will not be applied.'
            }
            break

        case ChangeRequestState.Approved:
            analysis.summary = `Approved with ${approvedCount}/${quorum} votes`
            analysis.details = `This change request reached the approval quorum and is ready to be applied.

Final vote count:
✓ Approved: ${approvedCount} (${approvedBy.join(', ')})
✗ Rejected: ${rejectedCount}${rejectedBy.length > 0 ? ` (${rejectedBy.join(', ')})` : ''}
Required quorum: ${quorum}

The change will be applied automatically.`
            break

        case ChangeRequestState.Applied:
            analysis.summary = `Applied successfully after ${approvedCount}/${quorum} approvals`
            analysis.details = `This change request was approved and successfully applied.

Final vote count:
✓ Approved: ${approvedCount} (${approvedBy.join(', ')})
✗ Rejected: ${rejectedCount}${rejectedBy.length > 0 ? ` (${rejectedBy.join(', ')})` : ''}
Required quorum: ${quorum}

Applied by: ${changeRequest.applied_by?.first_name || 'System'}`
            break

        case ChangeRequestState.Expired:
            analysis.summary = 'Expired without reaching quorum'
            analysis.details = `This change request expired before reaching the approval quorum.

Final vote count:
✓ Approved: ${approvedCount}${approvedBy.length > 0 ? ` (${approvedBy.join(', ')})` : ''}
✗ Rejected: ${rejectedCount}${rejectedBy.length > 0 ? ` (${rejectedBy.join(', ')})` : ''}
Required quorum: ${quorum}

The change request expired at ${changeRequest.expires_at} without reaching the required ${quorum} approval${quorum > 1 ? 's' : ''}.`
            break

        case ChangeRequestState.Failed:
            analysis.summary = `Application failed after ${approvedCount}/${quorum} approvals`
            analysis.details = `This change request was approved but failed during application.

Final vote count:
✓ Approved: ${approvedCount} (${approvedBy.join(', ')})
✗ Rejected: ${rejectedCount}${rejectedBy.length > 0 ? ` (${rejectedBy.join(', ')})` : ''}
Required quorum: ${quorum}

Error: ${changeRequest.apply_error || 'Unknown error'}`
            break
    }

    return analysis
}
