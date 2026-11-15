export class AsyncReaderWriterLock {
  private readers = 0;
  private writer = false;
  private writerWaiting = false;
  private readQueue: Array<() => void> = [];
  private writeQueue: Array<() => void> = [];

  async acquireRead(): Promise<void> {
    if (!this.writer && !this.writerWaiting) {
      this.readers++;
      return;
    }
    return new Promise((resolve) => {
      this.readQueue.push(() => {
        this.readers++;
        resolve();
      });
    });
  }

  releaseRead(): void {
    this.readers--;
    this.processQueue();
  }

  async acquireWrite(): Promise<void> {
    if (!this.writer && this.readers === 0) {
      this.writer = true;
      return;
    }
    this.writerWaiting = true;
    return new Promise((resolve) => {
      this.writeQueue.push(() => {
        this.writerWaiting = this.writeQueue.length > 0;
        this.writer = true;
        resolve();
      });
    });
  }

  releaseWrite(): void {
    this.writer = false;
    this.processQueue();
  }

  private processQueue(): void {
    if (this.writer || this.readers > 0) return;

    if (this.writeQueue.length > 0) {
      const next = this.writeQueue.shift();
      if (next) next();
    } else {
      while (this.readQueue.length > 0 && !this.writerWaiting) {
        const next = this.readQueue.shift();
        if (next) next();
      }
    }
  }
}
