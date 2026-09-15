import { MlEncryptedEnvelope } from './crypto'
import vector from './encryption-vector.json'

export const TrainingEncryptionVector = { ...vector, envelope: vector.envelope as MlEncryptedEnvelope }
