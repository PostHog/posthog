'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import Header from '@/components/Header'
import { useAuth } from '@/lib/auth'
import { sampleFiles } from '@/lib/data'
import { useAuthRedirect } from '@/lib/hooks'
import { posthog } from '@/lib/posthog'
import { formatFileSize, getFileIcon } from '@/lib/utils'
import { HedgeboxFile } from '@/types'

interface FilePageProps {
    params: {
        id: string
    }
}

export default function FilePage({ params }: FilePageProps): React.JSX.Element | null {
    const { user } = useAuth()
    const [file, setFile] = useState<HedgeboxFile | null>(null)
    const [isLoading, setIsLoading] = useState(true)
    const [showShareModal, setShowShareModal] = useState(false)
    const [isProcessing, setIsProcessing] = useState(false)
    const router = useRouter()

    useAuthRedirect()

    useEffect(() => {
        // Simulate finding the file by ID
        const foundFile = sampleFiles.find((f) => f.id === params.id)
        setFile(foundFile || null)
        setIsLoading(false)

        // Track file view
        if (foundFile) {
            posthog.capture('viewed_file', {
                file_id: foundFile.id,
                file_type: foundFile.type,
                file_size_b: foundFile.size,
            })
        }
    }, [params.id])

    if (!user) {return null}

    if (isLoading) {
        return (
            <div>
                <Header />
                <div className="container mx-auto px-4 py-8 max-w-4xl">
                    <div className="flex items-center justify-center py-20">
                        <span className="loading loading-spinner loading-lg" />
                    </div>
                </div>
            </div>
        )
    }

    if (!file) {
        return (
            <div>
                <Header />
                <div className="container mx-auto px-4 py-8 max-w-4xl">
                    <div className="text-center py-20">
                        <div className="text-8xl mb-4">🔍</div>
                        <h2 className="text-3xl font-bold mb-4">File not found</h2>
                        <p className="text-base-content/70 mb-6">
                            The file you're looking for doesn't exist or has been deleted.
                        </p>
                        <Link href="/files" className="btn btn-primary">
                            ← Back to Files
                        </Link>
                    </div>
                </div>
            </div>
        )
    }

    const handleDownload = (): void => {
        setIsProcessing(true)
        posthog.capture('downloaded_file', {
            file_id: file.id,
            file_type: file.type,
            file_size_b: file.size,
        })

        // Simulate download processing
        setTimeout(() => {
            setIsProcessing(false)
            // In a real app, this would trigger the actual download
        }, 2000)
    }

    const handleShare = (): void => {
        posthog.capture('shared_file', {
            file_id: file.id,
            file_type: file.type,
            file_size_b: file.size,
        })
        setShowShareModal(true)
    }

    const handleDelete = (): void => {
        if (confirm('Are you sure you want to delete this file? This action cannot be undone.')) {
            posthog.capture('deleted_file', {
                file_id: file.id,
                file_type: file.type,
                file_size_b: file.size,
            })
            router.push('/files')
        }
    }

    const copyShareLink = (): void => {
        const shareLink = file.sharedLink || `https://hedgebox.net/files/${file.id}/shared`
        navigator.clipboard.writeText(shareLink)
        posthog.capture('copied_share_link', {
            file_id: file.id,
        })
    }

    const getPreviewComponent = (): React.JSX.Element => {
        if (file.type.startsWith('image/')) {
            return (
                <div className="bg-base-200 rounded-lg p-8 text-center">
                    <div className="text-8xl mb-4">{getFileIcon(file.type)}</div>
                    <p className="text-base-content/70">Image preview would appear here</p>
                </div>
            )
        } else if (file.type === 'application/pdf') {
            return (
                <div className="bg-base-200 rounded-lg p-8 text-center">
                    <div className="text-8xl mb-4">{getFileIcon(file.type)}</div>
                    <p className="text-base-content/70">PDF preview would appear here</p>
                </div>
            )
        } else if (file.type.startsWith('video/')) {
            return (
                <div className="bg-base-200 rounded-lg p-8 text-center">
                    <div className="text-8xl mb-4">{getFileIcon(file.type)}</div>
                    <p className="text-base-content/70">Video preview would appear here</p>
                </div>
            )
        }
            return (
                <div className="bg-base-200 rounded-lg p-8 text-center">
                    <div className="text-8xl mb-4">{getFileIcon(file.type)}</div>
                    <p className="text-base-content/70">No preview available for this file type</p>
                </div>
            )
        
    }

    return (
        <div>
            <Header />

            <div className="container mx-auto px-4 py-8 max-w-4xl">
                {/* Breadcrumb */}
                <div className="breadcrumbs text-sm mb-6">
                    <ul>
                        <li>
                            <Link href="/files" className="link link-hover">
                                📁 Files
                            </Link>
                        </li>
                        <li className="text-base-content/70">{file.name}</li>
                    </ul>
                </div>

                {/* File Header */}
                <div className="card bg-base-100 shadow-lg mb-8">
                    <div className="card-body">
                        <div className="flex items-start justify-between mb-4">
                            <div className="flex items-center space-x-4">
                                <div className="text-6xl">{getFileIcon(file.type)}</div>
                                <div>
                                    <h1 className="text-3xl font-bold mb-2">{file.name}</h1>
                                    <div className="flex items-center space-x-4 text-base-content/70">
                                        <span>{formatFileSize(file.size)}</span>
                                        <span>•</span>
                                        <span>{file.type}</span>
                                        <span>•</span>
                                        <span>Uploaded {new Date(file.uploadedAt).toLocaleDateString()}</span>
                                    </div>
                                    {file.sharedLink && <div className="badge badge-secondary mt-2">🔗 Shared</div>}
                                </div>
                            </div>

                            <div className="flex space-x-2">
                                <button
                                    onClick={handleDownload}
                                    className={`btn btn-primary ${isProcessing ? 'loading' : ''}`}
                                    disabled={isProcessing}
                                >
                                    {isProcessing ? 'Processing...' : '📥 Download'}
                                </button>
                                <button onClick={handleShare} className="btn btn-secondary">
                                    🔗 Share
                                </button>
                                <div className="dropdown dropdown-end">
                                    <div tabIndex={0} role="button" className="btn btn-ghost">
                                        ⋮
                                    </div>
                                    <ul
                                        tabIndex={0}
                                        className="dropdown-content z-[1] menu p-2 shadow bg-base-100 rounded-lg w-40"
                                    >
                                        <li>
                                            <Link href="/files">📁 Back to Files</Link>
                                        </li>
                                        <li>
                                            <button onClick={handleDelete} className="text-error">
                                                🗑️ Delete
                                            </button>
                                        </li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                {/* File Preview */}
                <div className="card bg-base-100 shadow-lg mb-8">
                    <div className="card-body">
                        <h2 className="text-xl font-bold mb-4">Preview</h2>
                        {getPreviewComponent()}
                    </div>
                </div>

                {/* File Details */}
                <div className="card bg-base-100 shadow-lg">
                    <div className="card-body">
                        <h2 className="text-xl font-bold mb-4">File Details</h2>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <div className="stat">
                                    <div className="stat-title">File Name</div>
                                    <div className="stat-value text-lg">{file.name}</div>
                                </div>
                            </div>
                            <div>
                                <div className="stat">
                                    <div className="stat-title">File Size</div>
                                    <div className="stat-value text-lg">{formatFileSize(file.size)}</div>
                                </div>
                            </div>
                            <div>
                                <div className="stat">
                                    <div className="stat-title">File Type</div>
                                    <div className="stat-value text-lg">{file.type}</div>
                                </div>
                            </div>
                            <div>
                                <div className="stat">
                                    <div className="stat-title">Upload Date</div>
                                    <div className="stat-value text-lg">
                                        {new Date(file.uploadedAt).toLocaleDateString()}
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Share Modal */}
            {showShareModal && (
                <div className="modal modal-open">
                    <div className="modal-box">
                        <h3 className="font-bold text-lg mb-4">Share File</h3>
                        <p className="mb-4">Share this file with others using the link below:</p>

                        <div className="form-control mb-4">
                            <label className="label">
                                <span className="label-text">Share Link</span>
                            </label>
                            <div className="join">
                                <input
                                    type="text"
                                    value={file.sharedLink || `https://hedgebox.net/files/${file.id}/shared`}
                                    className="input input-bordered join-item flex-1"
                                    readOnly
                                />
                                <button onClick={copyShareLink} className="btn btn-primary join-item">
                                    📋 Copy
                                </button>
                            </div>
                        </div>

                        <div className="alert alert-info">
                            <svg
                                xmlns="http://www.w3.org/2000/svg"
                                fill="none"
                                viewBox="0 0 24 24"
                                className="stroke-current shrink-0 w-6 h-6"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth="2"
                                    d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                                 />
                            </svg>
                            <span>Anyone with this link can view and download this file.</span>
                        </div>

                        <div className="modal-action">
                            <button onClick={() => setShowShareModal(false)} className="btn">
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
