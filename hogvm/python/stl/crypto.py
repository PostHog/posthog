import hashlib


def md5Hex(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()


def sha256Hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()
