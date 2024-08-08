import hashlib
import hmac


def md5Hex(data: str) -> str:
    return hashlib.md5(data.encode()).hexdigest()


def sha256Hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def sha256HmacChainHex(data: list) -> str:
    if len(data) < 2:
        raise ValueError("Data array must contain at least two elements.")

    hmac_obj = hmac.new(data[0].encode(), data[1].encode(), hashlib.sha256)
    for i in range(2, len(data)):
        hmac_obj = hmac.new(hmac_obj.digest(), data[i].encode(), hashlib.sha256)

    return hmac_obj.hexdigest()
