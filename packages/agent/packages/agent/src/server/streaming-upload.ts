import { Buffer } from "node:buffer";
import {
  type ClientRequest,
  request as httpRequest,
  type IncomingHttpHeaders,
} from "node:http";
import { request as httpsRequest } from "node:https";
import { URL } from "node:url";

export interface StreamingUpload {
  write(chunk: Uint8Array): Promise<void>;
  close(): Promise<void>;
  abort(): Promise<void>;
  responsePromise: Promise<Response>;
}

export interface StreamingUploadFactoryInput {
  url: string;
  headers: Record<string, string>;
  abortController: AbortController;
}

export type StreamingUploadFactory = (
  input: StreamingUploadFactoryInput,
) => StreamingUpload;

function headersFromIncoming(headers: IncomingHttpHeaders): Headers {
  const result = new Headers();
  for (const [name, value] of Object.entries(headers)) {
    if (value === undefined) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        result.append(name, item);
      }
    } else {
      result.set(name, String(value));
    }
  }
  return result;
}

function abortError(): Error {
  const error = new Error("aborted");
  error.name = "AbortError";
  return error;
}

function writeRequestChunk(
  request: ClientRequest,
  chunk: Uint8Array,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const onError = (error: Error): void => {
      request.off("error", onError);
      reject(error);
    };
    request.once("error", onError);
    request.write(Buffer.from(chunk), (error?: Error | null) => {
      request.off("error", onError);
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
}

function closeRequest(request: ClientRequest): Promise<void> {
  return new Promise((resolve, reject) => {
    const onError = (error: Error): void => {
      request.off("error", onError);
      reject(error);
    };
    request.once("error", onError);
    request.end(() => {
      request.off("error", onError);
      resolve();
    });
  });
}

export function createNodeStreamingUpload({
  url,
  headers,
  abortController,
}: StreamingUploadFactoryInput): StreamingUpload {
  const parsedUrl = new URL(url);
  const requestFactory =
    parsedUrl.protocol === "https:"
      ? httpsRequest
      : parsedUrl.protocol === "http:"
        ? httpRequest
        : undefined;
  if (!requestFactory) {
    throw new Error(`Unsupported event ingest protocol: ${parsedUrl.protocol}`);
  }
  const request = requestFactory(parsedUrl, {
    method: "POST",
    headers,
  });

  let closed = false;
  const responsePromise = new Promise<Response>((resolve, reject) => {
    request.on("response", (response) => {
      const chunks: Buffer[] = [];
      response.on("data", (chunk: Buffer | string) => {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
      });
      response.on("end", () => {
        resolve(
          new Response(Buffer.concat(chunks), {
            status: response.statusCode ?? 0,
            statusText: response.statusMessage,
            headers: headersFromIncoming(response.headers),
          }),
        );
      });
      response.on("error", reject);
    });
    request.on("error", reject);
  });

  const abortRequest = (): void => {
    closed = true;
    if (!request.destroyed) {
      request.destroy(abortError());
    }
  };
  abortController.signal.addEventListener("abort", abortRequest, {
    once: true,
  });
  void responsePromise
    .finally(() => {
      abortController.signal.removeEventListener("abort", abortRequest);
    })
    .catch(() => undefined);

  return {
    async write(chunk: Uint8Array): Promise<void> {
      if (closed) {
        throw new Error("Cannot write to closed event ingest stream");
      }
      await writeRequestChunk(request, chunk);
    },
    async close(): Promise<void> {
      if (closed) {
        return;
      }
      closed = true;
      await closeRequest(request);
    },
    async abort(): Promise<void> {
      abortRequest();
    },
    responsePromise,
  };
}
