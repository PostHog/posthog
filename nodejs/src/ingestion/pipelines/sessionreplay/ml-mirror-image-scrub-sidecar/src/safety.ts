/**
 * NSFW/gore gate via onnxruntime-node. Model: image-safety-classifier-xs (SwiftFormer, 3.5M params,
 * MIT), 224x224 input, softmax over [NSFL, NSFW, SFW] baked into the graph — the output IS
 * probabilities. The gate runs on ORT like the other detectors so the whole scrub shares one ML
 * runtime, and the NSFL class is what makes the gate cover gore, not just nudity.
 */
import * as ort from 'onnxruntime-node'

import { numFromEnv } from './env.ts'
import { type Src, srcSharp } from './src-image.ts'

const SAFETY_SIZE = 224 // fixed model input; pixel values 0-255 (normalization is baked into the graph)
const ORT_THREADS = numFromEnv('ORT_THREADS', 1, 1, 32)

export interface SafetyModel {
    session: ort.InferenceSession
    inputName: string
    outputName: string
}

export async function loadSafety(modelPath: string): Promise<SafetyModel> {
    const session = await ort.InferenceSession.create(modelPath, {
        graphOptimizationLevel: 'all',
        intraOpNumThreads: ORT_THREADS,
        interOpNumThreads: 1,
        executionMode: 'sequential',
    })
    return { session, inputName: session.inputNames[0], outputName: session.outputNames[0] }
}

export interface SafetyScores {
    nsfl: number
    nsfw: number
    sfw: number
}

export async function classifySafety(model: SafetyModel, src: Src): Promise<SafetyScores> {
    const { data } = await srcSharp(src)
        .resize(SAFETY_SIZE, SAFETY_SIZE, { fit: 'fill' })
        .raw()
        .toBuffer({ resolveWithObject: true })
    const plane = SAFETY_SIZE * SAFETY_SIZE
    const chw = new Float32Array(3 * plane)
    for (let i = 0, p = 0; i < data.length; i += 3, p++) {
        chw[p] = data[i]
        chw[plane + p] = data[i + 1]
        chw[2 * plane + p] = data[i + 2]
    }
    const out = await model.session.run({
        [model.inputName]: new ort.Tensor('float32', chw, [1, 3, SAFETY_SIZE, SAFETY_SIZE]),
    })
    const probs = out[model.outputName].data as Float32Array
    return { nsfl: probs[0], nsfw: probs[1], sfw: probs[2] }
}
